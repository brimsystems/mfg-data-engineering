-- Hours and cost by work center, with each cell's share of the margin of the jobs
-- that ran through it (job contribution allocated by the cell's share of the
-- job's cost), under the pool rate and under the blended rate.

with cell_cost as (

    select h.job_id, h.work_center_id, left(h.work_center_id, 3) as work_center_group, h.source,
           h.setup_hours + h.run_hours + h.rework_hours as hours,
           (h.setup_hours + h.run_hours + h.rework_hours) * r.pool_rate as cost_pool,
           (h.setup_hours + h.run_hours + h.rework_hours) * r.blended_rate as cost_blended
    from {{ ref('int_labor_hours_by_job') }} h
    join {{ ref('stg_erp__jobs') }} j using (job_id)
    join {{ ref('int_rates') }} r on r.work_center_id = h.work_center_id and r.year = extract(year from j.release_date)

),

allocated as (

    select c.*, m.contribution * c.cost_pool / nullif(m.act_total_cost, 0) as contribution_share,
           m.price * c.cost_pool / nullif(m.act_total_cost, 0) as revenue_share,
           (m.price - m.act_total_cost_blended) * c.cost_blended / nullif(m.act_total_cost_blended, 0) as contribution_share_blended
    from cell_cost c
    join {{ ref('mart_margin_by_job') }} m using (job_id)

)

select
    a.work_center_group,
    a.work_center_id,
    w.work_center_type,
    w.monitored_flag,
    count(distinct job_id)                                           as jobs,
    sum(hours)                                                       as hours,
    sum(case when source = 'machine' then hours else 0 end)          as machine_hours,
    sum(case when source in ('clock', 'unrepairable') then hours else 0 end) as clock_hours,
    sum(case when source = 'scan' then hours else 0 end)             as scan_hours,
    sum(case when source = 'standard-fallback' then hours else 0 end) as fallback_hours,
    sum(case when source = 'unrepairable' then hours else 0 end)     as unrepairable_hours,
    sum(cost_pool)                                                   as cost_pool,
    sum(cost_blended)                                                as cost_blended,
    sum(revenue_share)                                               as revenue_allocated,
    sum(contribution_share)                                          as contribution_allocated,
    sum(contribution_share) / nullif(sum(revenue_share), 0)          as margin_on_price,
    sum(contribution_share_blended) / nullif(sum(revenue_share), 0)  as margin_on_price_blended
from allocated a
join {{ ref('stg_erp__work_centers') }} w using (work_center_id)
group by 1, 2, 3, 4
