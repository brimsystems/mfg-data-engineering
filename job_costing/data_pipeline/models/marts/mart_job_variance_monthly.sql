-- The period summary by completion month, from the job variance mart: the Month grouping
-- of the Job Variance report and the dashboard's 13-month shortfall chart. Grain: month.

select
    completion_month,
    count(*)                                                          as jobs_completed,
    sum(quantity)                                                     as pieces_shipped,
    sum(price)                                                        as revenue,
    sum(contribution) / nullif(sum(price), 0)                         as margin_on_price,
    avg(case when below_target then 1.0 else 0.0 end)                 as below_target_share,
    avg(case when losing then 1.0 else 0.0 end)                       as losing_share,
    sum(shortfall)                                                    as shortfall,
    median(ratio_total)                                               as actual_over_estimate_median,
    sum(measured_cost) / nullif(sum(act_total), 0)                    as cost_measured_share,
    sum(alloc_setup)                                                  as shortfall_setup,
    sum(alloc_run)                                                    as shortfall_run,
    sum(alloc_material)                                               as shortfall_material,
    sum(alloc_outside)                                                as shortfall_outside,
    sum(alloc_scrap_rework)                                           as shortfall_scrap_rework,
    sum(alloc_price)                                                  as shortfall_price,
    sum(alloc_not_attributable)                                       as shortfall_not_attributable
from {{ ref('mart_job_variance') }}
group by 1
