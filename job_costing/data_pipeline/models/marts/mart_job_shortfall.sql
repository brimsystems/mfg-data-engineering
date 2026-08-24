-- Why each job landed where it did against target. For every job, the shortfall to
-- target contribution (target margin on price less the margin earned) splits
-- exactly into the price at the estimate and the actual cost over the estimate by
-- element. The estimate is re-costed at today's prices: its hours at the job's own
-- pool rate (actual labor dollars over actual hours) and its material at the part's
-- need at the job's issue price, so the labor elements are hours and the material
-- element is usage. What prices and rates moved since the quote sits in the price
-- component, which is where the repricing queue picks it up:
--
--   shortfall = price component  (target contribution less the contribution the estimate promised)
--             + material over estimate
--             + setup hours over estimate x rate
--             + run hours over estimate x rate
--             + outside processing over estimate
--             + scrap material + rework hours x rate
--
-- Each element's overrun is then assigned to a named cause where the data shows
-- one, and to "not attributable" where it does not. Elements that came in under
-- estimate are kept as offsets, so the causes, the not-attributable amount and the
-- offsets add back to the shortfall. The primary cause is the largest assigned
-- amount on the job, and it maps to the action the owner and estimator work from.
-- Grain: job (cleaned history and engagement-period jobs).

with j as (

    select * from {{ ref('mart_margin_by_job') }}

),

-- the customer whose revision changes are worked after release: the most change orders on the customer record
co_customer as (

    select customer_id from {{ ref('stg_erp__customers') }}
    order by change_order_count_12m desc, customer_id limit 1

),

-- the first job released after a revision change on the part
revision_first as (

    select job_id,
           lag(revision) over (partition by part_number order by release_date, job_id) is not null
           and revision <> lag(revision) over (partition by part_number order by release_date, job_id) as first_after_revision
    from {{ ref('stg_erp__jobs') }}

),

older_machines as (

    select work_center_id from {{ ref('stg_erp__work_centers') }}
    where install_year <= {{ var('older_machine_install_year') }}

),

older_run as (

    select job_id, sum(run_hours) as older_machine_run_hours
    from {{ ref('int_labor_hours_by_job') }}
    where work_center_id in (select work_center_id from older_machines)
    group by 1

),

-- how much slower the older machines run the same part, measured on the parts that ran on both
older_factor as (

    select median(older_over_newer) as older_over_newer
    from {{ ref('int_machine_age_cycle') }}
    where older_jobs >= 1 and newer_jobs >= 1

),

-- the routing standard the estimate was built on against the cycle the machines measured
-- (the standard refresh log), for the parts whose standard was below the measured cycle
standard_gap as (

    select part_number,
           sum(measured_run_min) / nullif(sum(old_std_run_min), 0)           as run_measured_over_standard,
           sum(measured_setup_hours) / nullif(sum(old_std_setup_hours), 0)   as setup_measured_over_standard,
           min(effective_date)                                               as refreshed_on
    from {{ ref('stg_remediation__standard_update_log') }}
    group by 1

),

material_today as (

    select job_id, need_at_issue_price from {{ ref('int_material_by_job') }}

),

-- outside processing that could not be tied to a job, spread over the month's jobs so the ledger reconciles
osp_allocated as (

    select job_id, sum(amount) as osp_allocated
    from {{ ref('fct_job_cost_elements') }}
    where version <> 'raw' and element = 'outside' and source = 'GL residual, allocated'
    group by 1

),

plating as (

    select distinct job_id from {{ ref('int_osp_by_job') }}
    where job_id is not null and service_type = 'plating'

),

setup_cells as (

    select distinct job_id from {{ ref('int_labor_hours_by_job') }}
    where left(work_center_id, 3) in ('MTN', 'FAX') and setup_hours > 0

),

-- what a normal job looks like in the analysis year, so a cause is sized as the excess over normal
typical as (

    select
        median(case when material_spec not like 'Ti %' and material_spec not like 'Inconel %' then run_hours_ratio end) as typ_run_ratio,
        median(case when not small_lot then setup_hours_ratio end)                                                   as typ_setup_ratio,
        median(labor_hours_ratio)                                                                                    as typ_labor_ratio
    from j
    where release_year = {{ var('analysis_year') }} and est_run_hours > 0

),

base as (

    select
        j.job_id, j.version, j.part_number, j.part_family, j.customer_id, j.customer_name, j.job_type, j.material_spec,
        j.quantity, j.small_lot, j.release_date, j.completed_date, j.due_date, j.release_year, j.status,
        j.price, j.act_total_cost, j.contribution, j.margin_on_price, j.estimated_margin_on_price, j.coverage,
        j.est_setup_hours, j.est_run_hours, j.act_setup_hours, j.act_run_hours, coalesce(j.act_rework_hours, 0) as act_rework_hours,
        coalesce(j.act_labor / nullif(j.act_labor_hours, 0),
                 j.est_labor / nullif(j.est_setup_hours + j.est_run_hours, 0))                          as rate,
        {{ var('target_markup') }} / (1 + {{ var('target_markup') }})                                  as target_margin,
        j.est_material, j.est_outside, j.act_material, j.act_outside, j.act_scrap,
        -- the estimate's material at the price of the day: the part's need at the job's issue price.
        -- What the price moved since the quote belongs to the price, not to material usage.
        coalesce(mt.need_at_issue_price, j.est_material)                                               as est_material_today,
        coalesce(oa.osp_allocated, 0)                                                                  as osp_allocated,
        j.customer_id = (select customer_id from co_customer)                                          as change_order_customer,
        coalesce(r.first_after_revision, false)                                                        as first_after_revision,
        j.material_spec like 'Ti %' or j.material_spec like 'Inconel %'                                as difficult_alloy,
        coalesce(o.older_machine_run_hours, 0)                                                         as older_machine_run_hours,
        p.job_id is not null                                                                           as plated,
        s.job_id is not null                                                                           as setup_on_mtn_fax,
        -- the standard understated the cycle on this job only if the job was estimated before the refresh
        case when sg.refreshed_on is null or j.release_date < sg.refreshed_on then greatest(coalesce(sg.run_measured_over_standard, 1) - 1, 0) else 0 end   as run_standard_short,
        case when sg.refreshed_on is null or j.release_date < sg.refreshed_on then greatest(coalesce(sg.setup_measured_over_standard, 1) - 1, 0) else 0 end as setup_standard_short
    from j
    left join revision_first r using (job_id)
    left join older_run o using (job_id)
    left join plating p using (job_id)
    left join setup_cells s using (job_id)
    left join standard_gap sg on sg.part_number = j.part_number
    left join material_today mt using (job_id)
    left join osp_allocated oa using (job_id)

),

components as (

    select b.*,
        b.est_material_today + (b.est_setup_hours + b.est_run_hours) * b.rate + b.est_outside            as est_cost_at_pool,
        b.target_margin * b.price - b.contribution                                                     as shortfall,
        b.target_margin * b.price - (b.price - (b.est_material_today + (b.est_setup_hours + b.est_run_hours) * b.rate + b.est_outside)) as c_price,
        b.act_material - b.est_material_today                                                          as c_material,
        (b.act_setup_hours - b.est_setup_hours) * b.rate                                               as c_setup,
        (b.act_run_hours - b.est_run_hours) * b.rate                                                   as c_run,
        b.act_outside - b.est_outside                                                                  as c_outside,
        b.act_scrap + b.act_rework_hours * b.rate                                                      as c_scrap_rework
    from base b

),

assigned as (

    select c.*,
        -- price at the estimate: by how the price was set
        case when c.c_price > 0 and c.job_type = 'repeat' then c.c_price else 0 end                      as k_standing_price,
        case when c.c_price > 0 and c.job_type = 'new' then c.c_price else 0 end                         as k_quoted_price,
        case when c.c_price > 0 and c.job_type = 'own_product' then c.c_price else 0 end                 as k_list_price,
        -- setup hours: revision work on the change-order customer, the first run after a revision, small lots on mill-turn and 5-axis
        case when c.c_setup > 0 and c.change_order_customer
             then least(c.c_setup, greatest(0, c.act_setup_hours - c.est_setup_hours * t.typ_labor_ratio) * c.rate) else 0 end as k_co_setup,
        case when c.c_setup > 0 and not c.change_order_customer and c.first_after_revision
             then least(c.c_setup, greatest(0, c.act_setup_hours - c.est_setup_hours * t.typ_setup_ratio) * c.rate) else 0 end as k_revision,
        case when c.c_setup > 0 and not c.change_order_customer and not c.first_after_revision and c.small_lot and c.setup_on_mtn_fax
             then least(c.c_setup, greatest(0, c.act_setup_hours - c.est_setup_hours * t.typ_setup_ratio) * c.rate) else 0 end as k_small_lot,
        -- run hours: revision work, titanium and Inconel, the older machines
        case when c.c_run > 0 and c.change_order_customer
             then least(c.c_run, greatest(0, c.act_run_hours - c.est_run_hours * t.typ_labor_ratio) * c.rate) else 0 end as k_co_run,
        case when c.c_run > 0 and not c.change_order_customer and c.difficult_alloy
             then least(c.c_run, greatest(0, c.act_run_hours - c.est_run_hours * t.typ_run_ratio) * c.rate) else 0 end as k_alloy,
        -- outside processing on plated jobs
        case when c.c_outside > 0 then least(c.c_outside, c.osp_allocated) else 0 end                    as k_osp_allocated,
        case when c.c_outside > 0 and c.plated then greatest(0, c.c_outside - least(c.c_outside, c.osp_allocated)) else 0 end as k_plating,
        case when c.c_outside > 0 and not c.plated then greatest(0, c.c_outside - least(c.c_outside, c.osp_allocated)) else 0 end as k_vendor_price,
        greatest(c.c_material, 0)                                                                        as k_material,
        greatest(c.c_scrap_rework, 0)                                                                    as k_scrap_rework,
        f.older_over_newer
    from components c
    cross join typical t
    cross join older_factor f

),

older as (

    select a.*,
        case when a.c_run > 0
             then greatest(0, least(a.c_run - a.k_co_run - a.k_alloy,
                                    a.older_machine_run_hours * (1 - 1 / nullif(a.older_over_newer, 0)) * a.rate)) else 0 end as k_older_machine
    from assigned a

),

final as (

    -- the standard below the measured cycle takes what the specific causes leave
    select o.*,
        case when o.c_run > 0
             then greatest(0, least(o.c_run - o.k_co_run - o.k_alloy - o.k_older_machine,
                                    o.est_run_hours * o.run_standard_short * o.rate)) else 0 end
        + case when o.c_setup > 0
             then greatest(0, least(o.c_setup - o.k_co_setup - o.k_revision - o.k_small_lot,
                                    o.est_setup_hours * o.setup_standard_short * o.rate)) else 0 end as k_standard
    from older o

)

select
    f.job_id, f.version, f.part_number, f.part_family, f.customer_id, f.customer_name, f.job_type, f.material_spec,
    f.quantity, f.small_lot, f.release_date, f.completed_date, f.due_date, f.release_year, f.status,
    f.price, f.act_total_cost, f.est_cost_at_pool, f.est_material, f.est_material_today, f.act_material, f.contribution, f.margin_on_price, f.estimated_margin_on_price, f.coverage, f.rate,
    f.change_order_customer, f.first_after_revision, f.difficult_alloy, f.older_machine_run_hours, f.plated, f.setup_on_mtn_fax,
    f.run_standard_short, f.setup_standard_short, f.est_setup_hours, f.est_run_hours, f.act_setup_hours, f.act_run_hours, f.act_rework_hours,
    f.margin_on_price < f.target_margin - 0.02                                                          as below_target,
    f.contribution < 0                                                                                  as loss,
    f.shortfall,
    -- the split by element
    f.c_price, f.c_material, f.c_setup, f.c_run, f.c_outside, f.c_scrap_rework,
    -- the split by cause
    f.k_standing_price  as cause_standing_price,
    f.k_quoted_price    as cause_quoted_price,
    f.k_list_price      as cause_list_price,
    f.k_co_setup + f.k_co_run as cause_revision_work_unbilled,
    f.k_revision        as cause_first_run_after_revision,
    f.k_small_lot       as cause_small_lot_setup,
    f.k_alloy           as cause_alloy_run_hours,
    f.k_older_machine   as cause_older_machine,
    f.k_standard        as cause_standard_below_cycle,
    f.k_plating         as cause_plating_rate,
    f.k_vendor_price    as cause_vendor_price,
    f.k_osp_allocated   as cause_osp_allocated,
    f.k_material        as cause_material,
    f.k_scrap_rework    as cause_scrap_rework,
    greatest(f.c_setup, 0) - f.k_co_setup - f.k_revision - f.k_small_lot
      + greatest(f.c_run, 0) - f.k_co_run - f.k_alloy - f.k_older_machine - f.k_standard
      + greatest(f.c_outside, 0) - f.k_osp_allocated - f.k_plating - f.k_vendor_price                   as not_attributable,
    least(f.c_price, 0) + least(f.c_material, 0) + least(f.c_setup, 0) + least(f.c_run, 0)
      + least(f.c_outside, 0)                                                                           as offsets
from final f
