-- Every job's cost by element and by source, in three versions: raw, as the ERP
-- had it; cleaned, the history corrected; restructured, the engagement-period
-- jobs under the new process. One row per job, version, element and source, so
-- coverage (the measured share of cost) can be computed at any grain. Labor rows
-- carry their work center.

with jobs as (

    select j.*, extract(year from j.release_date) as release_year,
           case when j.released_after_config then 'restructured' else 'cleaned' end as corrected_version
    from {{ ref('stg_erp__jobs') }} j

),

blended as (

    select year, max(blended_rate) as blended_rate from {{ ref('int_rates') }} group by 1

),

-- raw: the ERP's own figures
raw_labor as (

    select l.job_id, 'labor' as element, 'erp' as source, null::varchar as work_center_id, sum(l.hours) as hours,
           sum(l.hours * b.blended_rate) as amount, 1.0 as confidence
    from {{ ref('stg_erp__labor_transactions') }} l
    join blended b on b.year = extract(year from l.clock_on)
    where l.job_id is not null
    group by 1

),

raw_material as (

    select job_id, 'material' as element, 'erp' as source, null::varchar as work_center_id, null::double as hours, sum(value) as amount, 1.0 as confidence
    from {{ ref('stg_erp__material_transactions') }}
    group by 1

),

raw_outside as (

    select job_id, 'outside' as element, 'erp' as source, null::varchar as work_center_id, null::double as hours, sum(invoice_amount) as amount, 1.0 as confidence
    from {{ ref('stg_erp__outside_processing') }}
    where job_id is not null and invoice_amount is not null
    group by 1

),

raw as (

    select j.job_id, 'raw' as version, e.element, e.source, e.work_center_id, e.hours, e.amount, e.confidence
    from jobs j
    join (select * from raw_labor union all select * from raw_material union all select * from raw_outside) e using (job_id)

),

-- corrected: labor by source at the pool rate of the year
corr_labor as (

    select h.job_id, 'labor' as element, h.source, h.work_center_id, h.setup_hours + h.run_hours + h.rework_hours as hours,
           (h.setup_hours + h.run_hours + h.rework_hours) * r.pool_rate as amount, h.confidence
    from {{ ref('int_labor_hours_by_job') }} h
    join jobs j using (job_id)
    join {{ ref('int_rates') }} r on r.work_center_id = h.work_center_id and r.year = j.release_year

),

corr_material as (

    select job_id, 'material' as element, m.material_source as source, null::varchar as work_center_id, null::double as hours,
           m.material_corrected as amount, m.material_confidence as confidence
    from {{ ref('int_material_by_job') }} m
    where m.material_corrected <> 0

),

corr_outside as (

    select job_id, 'outside' as element,
           case when source = 'job number on the purchase order' then 'PO' else 'PO, attributed' end as source,
           null::varchar as work_center_id, null::double as hours, sum(amount) as amount, avg(confidence) as confidence
    from {{ ref('int_osp_by_job') }}
    where job_id is not null
    group by 1, 2, 3, 4

),

-- the lines that could not be attributed stay in the GL; they are spread over the
-- month's jobs with outside processing so the total reconciles with the ledger
gl_residual as (

    select date_trunc('month', order_date) as month, sum(amount) as residual_amount
    from {{ ref('int_osp_by_job') }}
    where job_id is null
    group by 1

),

corr_outside_residual as (

    select o.job_id, 'outside' as element, 'GL residual, allocated' as source, null::varchar as work_center_id, null::double as hours,
           g.residual_amount * o.amount / sum(o.amount) over (partition by o.month) as amount, 0.0 as confidence
    from (select job_id, date_trunc('month', order_date) as month, sum(amount) as amount
          from {{ ref('int_osp_by_job') }} where job_id is not null group by 1, 2) o
    join gl_residual g using (month)

),

corr_scrap as (

    select job_id, 'scrap' as element, 'issue' as source, null::varchar as work_center_id, null::double as hours, scrap_material as amount, 1.0 as confidence
    from {{ ref('int_scrap_by_job') }}
    where scrap_material > 0

),

corrected as (

    select j.job_id, j.corrected_version as version, e.element, e.source, e.work_center_id, e.hours, e.amount, e.confidence
    from jobs j
    join (select * from corr_labor union all select * from corr_material union all select * from corr_outside
          union all select * from corr_outside_residual union all select * from corr_scrap) e using (job_id)

)

select job_id, version, element, source, work_center_id, hours, amount, confidence,
       source in ('machine', 'clock', 'scan', 'issue', 'PO', 'PO, attributed', 'issue, corrected to part need') as measured
from raw
union all
select job_id, version, element, source, work_center_id, hours, amount, confidence,
       source in ('machine', 'clock', 'scan', 'issue', 'PO', 'PO, attributed', 'issue, corrected to part need') as measured
from corrected
