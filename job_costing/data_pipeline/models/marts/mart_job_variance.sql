-- The job variance mart the reporting layer's Job Cost dashboard and Job Variance report
-- read. One row per completed job: estimated and actual cost by element, the ratio of
-- each, margin at estimate and realized, and for a job below target its shortfall
-- allocated to elements by the reporting layer's rule:
--
--   shortfall = (target margin - actual margin) x price, on jobs below target margin
--   the part of it the elements over estimate can carry is allocated to them in
--   proportion to each element's overrun (actual less estimate where actual is higher);
--   the rest is "price below cost plus target"; and where no element carries at least
--   shortfall_dominance_share of the overrun, the allocated part is "not attributable".
--
-- The estimate is the one on the job: its material, its outside processing, and its setup
-- and run hours at the job's work-center pool rate, so the labor elements compare hours.
-- Grain: completed job.

with m as (

    select * from {{ ref('mart_margin_by_job') }}
    where status = 'completed'

),

s as (

    select job_id, rate, est_material_today, {{ var('target_markup') }} / (1 + {{ var('target_markup') }}) as target_margin from {{ ref('mart_job_shortfall') }}

),

j as (

    select job_id, revision_changes_after_release, change_order_billed, change_order_amount from {{ ref('stg_erp__jobs') }}

),

base as (

    select
        m.job_id, m.part_number, m.part_family, m.customer_id, m.customer_name, m.job_type, m.material_spec,
        case when m.material_spec like 'AL %' then 'Aluminum'
             when m.material_spec like 'SS %' then 'Stainless'
             when m.material_spec like 'Ti %' then 'Titanium'
             when m.material_spec like 'Inconel %' then 'Inconel'
             when m.material_spec like '4140 %' or m.material_spec like '1018 %' then 'Steel'
             else 'Brass and plastics' end                                             as material_group,
        m.quantity,
        case when m.quantity < 25 then 'Under 25' when m.quantity <= 100 then '25-100'
             when m.quantity <= 500 then '100-500' else 'Over 500' end                  as lot_band_setup,
        m.infrequent_part,
        m.release_date, m.completed_date, date_trunc('month', m.completed_date)          as completion_month,
        m.estimator_id, m.primary_work_center_group, m.price, m.coverage,
        j.revision_changes_after_release, j.change_order_billed, j.change_order_amount,
        s.target_margin, s.rate,
        m.est_setup_hours, m.act_setup_hours, m.est_run_hours, m.act_run_hours,
        m.est_setup_hours * s.rate                                                       as est_setup,
        m.act_setup_hours * s.rate                                                       as act_setup,
        m.est_run_hours * s.rate                                                         as est_run,
        m.act_run_hours * s.rate                                                         as act_run,
        m.est_material                                                                   as est_material,
        m.act_material                                                                   as act_material,
        m.est_outside                                                                    as est_outside,
        m.act_outside                                                                    as act_outside,
        0.0                                                                              as est_scrap_rework,
        m.act_scrap + coalesce(m.act_rework_hours, 0) * s.rate                           as act_scrap_rework,
        m.act_total_cost                                                                 as act_total,
        m.contribution, m.margin_on_price                                                as act_margin
    from m
    join s using (job_id)
    join j using (job_id)

),

measures as (

    select b.*,
        b.est_setup + b.est_run + b.est_material + b.est_outside                          as est_total,
        b.act_setup - b.est_setup                                                         as var_setup,
        b.act_run - b.est_run                                                             as var_run,
        b.act_material - b.est_material                                                   as var_material,
        b.act_outside - b.est_outside                                                     as var_outside,
        b.act_scrap_rework                                                                as var_scrap_rework,
        b.act_setup / nullif(b.est_setup, 0)                                              as ratio_setup,
        b.act_run / nullif(b.est_run, 0)                                                  as ratio_run,
        b.act_material / nullif(b.est_material, 0)                                        as ratio_material,
        b.act_outside / nullif(b.est_outside, 0)                                          as ratio_outside,
        b.act_margin < b.target_margin                                                    as below_target,
        b.contribution < 0                                                                as losing,
        case when b.act_margin < b.target_margin then b.target_margin * b.price - b.contribution else 0 end as shortfall
    from base b

),

overrun as (

    select m.*,
        (m.price - m.est_total) / nullif(m.price, 0)                                      as est_margin,
        m.act_total / nullif(m.est_total, 0)                                              as ratio_total,
        greatest(m.var_setup, 0) + greatest(m.var_run, 0) + greatest(m.var_material, 0)
          + greatest(m.var_outside, 0) + greatest(m.var_scrap_rework, 0)                  as overrun,
        greatest(greatest(m.var_setup, 0), greatest(m.var_run, 0), greatest(m.var_material, 0),
                 greatest(m.var_outside, 0), greatest(m.var_scrap_rework, 0))             as largest_overrun
    from measures m

),

allocated as (

    select o.*,
        least(o.shortfall, o.overrun)                                                     as attributable,
        o.overrun > 0 and o.largest_overrun < {{ var('shortfall_dominance_share') }} * o.overrun as no_dominant
    from overrun o

)

select
    a.*,
    case when a.overrun > 0 and not a.no_dominant then a.attributable * greatest(a.var_setup, 0) / a.overrun else 0 end        as alloc_setup,
    case when a.overrun > 0 and not a.no_dominant then a.attributable * greatest(a.var_run, 0) / a.overrun else 0 end          as alloc_run,
    case when a.overrun > 0 and not a.no_dominant then a.attributable * greatest(a.var_material, 0) / a.overrun else 0 end     as alloc_material,
    case when a.overrun > 0 and not a.no_dominant then a.attributable * greatest(a.var_outside, 0) / a.overrun else 0 end      as alloc_outside,
    case when a.overrun > 0 and not a.no_dominant then a.attributable * greatest(a.var_scrap_rework, 0) / a.overrun else 0 end as alloc_scrap_rework,
    a.shortfall - a.attributable                                                                                              as alloc_price,
    case when a.no_dominant then a.attributable else 0 end                                                                    as alloc_not_attributable,
    a.coverage * a.act_total                                                                                                  as measured_cost
from allocated a
