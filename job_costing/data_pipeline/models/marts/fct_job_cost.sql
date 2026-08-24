-- One row per job and version: estimate by element, actual by element, variance,
-- contribution and margin, coverage and the source tags behind each element.

with elements as (

    select job_id, version,
           sum(case when element = 'material' then amount else 0 end)                       as act_material,
           sum(case when element = 'labor' then amount else 0 end)                          as act_labor,
           sum(case when element = 'labor' then hours else 0 end)                           as act_labor_hours,
           sum(case when element = 'outside' then amount else 0 end)                        as act_outside,
           sum(case when element = 'scrap' then amount else 0 end)                          as act_scrap,
           sum(amount)                                                                      as act_total_cost,
           sum(case when measured then amount else 0 end)                                   as measured_cost,
           sum(case when source in ('standard-fallback', 'GL residual, allocated') then amount else 0 end) as fallback_cost,
           sum(case when source = 'unrepairable' then amount else 0 end)                    as unrepairable_cost,
           sum(case when element = 'labor' and source = 'machine' then hours else 0 end)    as machine_hours,
           sum(case when element = 'labor' and source in ('clock', 'unrepairable') then hours else 0 end) as clock_hours,
           sum(case when element = 'labor' and source = 'scan' then hours else 0 end)       as scan_hours,
           sum(case when element = 'labor' and source = 'standard-fallback' then hours else 0 end) as fallback_hours,
           sum(case when element = 'labor' and source = 'unrepairable' then hours else 0 end) as unrepairable_hours,
           string_agg(distinct case when element = 'labor' then source end, ', ' order by case when element = 'labor' then source end) as labor_sources,
           max(case when element = 'material' then source end)                              as material_source,
           string_agg(distinct case when element = 'outside' then source end, ', ')          as outside_source,
           sum(amount * confidence) / nullif(sum(amount), 0)                                as cost_confidence
    from {{ ref('fct_job_cost_elements') }}
    group by 1, 2

),

hours_split as (

    select job_id,
           sum(setup_hours) as act_setup_hours, sum(run_hours) as act_run_hours, sum(rework_hours) as act_rework_hours
    from {{ ref('int_labor_hours_by_job') }}
    group by 1

),

versions as (

    select job_id, 'raw' as version from {{ ref('stg_erp__jobs') }}
    union all
    select job_id, case when released_after_config then 'restructured' else 'cleaned' end from {{ ref('stg_erp__jobs') }}

)

select
    v.job_id,
    v.version,
    j.part_number,
    j.customer_id,
    j.job_type,
    j.quantity,
    j.release_date,
    j.completed_date,
    j.due_date,
    j.status,
    j.price,
    -- estimate
    case when v.version = 'raw' then case when j.est_total_cost is not null then 'job' else 'none' end else e.estimate_source end as estimate_source,
    case when v.version = 'raw' then j.est_material else e.est_material end             as est_material,
    case when v.version = 'raw' then j.est_setup_hours else e.est_setup_hours end       as est_setup_hours,
    case when v.version = 'raw' then j.est_run_hours else e.est_run_hours end           as est_run_hours,
    case when v.version = 'raw' then j.est_total_cost - j.est_material - j.est_outside else e.est_labor end as est_labor,
    case when v.version = 'raw' then j.est_outside else e.est_outside end               as est_outside,
    case when v.version = 'raw' then j.est_total_cost else e.est_total_cost end         as est_total_cost,
    case when v.version = 'raw' then 1.0 else e.estimate_confidence end                 as estimate_confidence,
    e.estimator_id,
    e.estimate_basis,
    -- actual
    coalesce(el.act_material, 0)                                                        as act_material,
    coalesce(el.act_labor, 0)                                                           as act_labor,
    coalesce(el.act_labor_hours, 0)                                                     as act_labor_hours,
    case when v.version = 'raw' then null else hs.act_setup_hours end                   as act_setup_hours,
    case when v.version = 'raw' then null else hs.act_run_hours end                     as act_run_hours,
    case when v.version = 'raw' then null else hs.act_rework_hours end                  as act_rework_hours,
    coalesce(el.act_outside, 0)                                                         as act_outside,
    coalesce(el.act_scrap, 0)                                                           as act_scrap,
    coalesce(el.act_total_cost, 0)                                                      as act_total_cost,
    -- variance and margin
    coalesce(el.act_total_cost, 0) - (case when v.version = 'raw' then j.est_total_cost else e.est_total_cost end) as variance_total,
    coalesce(el.act_material, 0) - (case when v.version = 'raw' then j.est_material else e.est_material end)      as variance_material,
    coalesce(el.act_labor, 0) - (case when v.version = 'raw' then j.est_total_cost - j.est_material - j.est_outside else e.est_labor end) as variance_labor,
    coalesce(el.act_outside, 0) - (case when v.version = 'raw' then j.est_outside else e.est_outside end)         as variance_outside,
    j.price - coalesce(el.act_total_cost, 0)                                            as contribution,
    (j.price - coalesce(el.act_total_cost, 0)) / nullif(j.price, 0)                     as margin_on_price,
    j.price / nullif(coalesce(el.act_total_cost, 0), 0) - 1                             as markup_on_cost,
    (j.price - (case when v.version = 'raw' then j.est_total_cost else e.est_total_cost end)) / nullif(j.price, 0) as estimated_margin_on_price,
    -- coverage and sources (fallback covers the routing standard and the allocated ledger residual)
    coalesce(el.measured_cost, 0) / nullif(el.act_total_cost, 0)                        as coverage,
    coalesce(el.fallback_cost, 0) / nullif(el.act_total_cost, 0)                        as fallback_share,
    coalesce(el.unrepairable_cost, 0) / nullif(el.act_total_cost, 0)                    as unrepairable_share,
    el.machine_hours,
    el.clock_hours,
    el.scan_hours,
    el.fallback_hours,
    el.unrepairable_hours,
    el.labor_sources,
    el.material_source,
    el.outside_source,
    el.cost_confidence,
    -- flags: an element more than fifteen percent over its estimate
    coalesce(el.act_material, 0) > 1.15 * (case when v.version = 'raw' then j.est_material else e.est_material end) as flag_material,
    coalesce(el.act_labor, 0) > 1.15 * (case when v.version = 'raw' then j.est_total_cost - j.est_material - j.est_outside else e.est_labor end) as flag_labor,
    coalesce(el.act_outside, 0) > 1.15 * (case when v.version = 'raw' then j.est_outside else e.est_outside end) + 1 as flag_outside
from versions v
join {{ ref('stg_erp__jobs') }} j using (job_id)
left join elements el using (job_id, version)
left join {{ ref('int_estimate_by_job') }} e using (job_id)
left join hours_split hs using (job_id)
