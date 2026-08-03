-- Contribution and margin by customer, from the corrected job cost.

select
    customer_id, customer_name, industry,
    count(*)                                                         as jobs,
    sum(quantity)                                                    as pieces,
    sum(price)                                                       as revenue,
    sum(est_total_cost)                                              as estimated_cost,
    sum(act_total_cost)                                              as actual_cost,
    sum(act_material)                                                as actual_material,
    sum(act_labor)                                                   as actual_labor,
    sum(act_outside)                                                 as actual_outside,
    sum(act_scrap)                                                   as actual_scrap,
    sum(act_labor_hours)                                             as labor_hours,
    sum(contribution)                                                as contribution,
    sum(contribution) / nullif(sum(price), 0)                        as margin_on_price,
    sum(price) / nullif(sum(act_total_cost), 0) - 1                  as markup_on_cost,
    (sum(price) - sum(est_total_cost)) / nullif(sum(price), 0)       as estimated_margin_on_price,
    sum(act_total_cost_blended)                                      as actual_cost_blended,
    (sum(price) - sum(act_total_cost_blended)) / nullif(sum(price), 0) as margin_on_price_blended,
    avg(margin_on_price)                                             as mean_job_margin,
    median(margin_on_price)                                          as median_job_margin,
    sum(case when contribution < 0 then 1 else 0 end) / count(*)     as share_negative,
    sum(case when margin_on_price < {{ var('target_markup') }} / (1 + {{ var('target_markup') }}) - 0.02 then 1 else 0 end) / count(*) as share_below_target,
    sum(measured_cost) / nullif(sum(act_total_cost), 0)              as coverage
from (select m.*, m.coverage * m.act_total_cost as measured_cost from {{ ref('mart_margin_by_job') }} m) m

group by 1, 2, 3
