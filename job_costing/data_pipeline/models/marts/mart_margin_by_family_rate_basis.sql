-- Margin by part family on the analysis year's jobs, costed two ways: every labor
-- hour at the blended shop rate of its year, and at the work-center pool rates
-- (the standard margin). Where the pools cost a family more than the blended rate
-- did, the difference is what the blended rate left out of that family's cost, and
-- at the target markup, out of its price. Grain: part family.

with f as (

    select
        part_family,
        count(*)                                                         as jobs,
        sum(price)                                                       as revenue,
        sum(act_total_cost_blended)                                      as cost_at_blended_rate,
        sum(act_total_cost)                                              as cost_at_pool_rates,
        sum(act_labor_hours)                                             as labor_hours
    from {{ ref('mart_margin_by_job') }}
    where release_year = {{ var('analysis_year') }}
    group by 1

)

select
    part_family,
    jobs,
    revenue,
    labor_hours,
    cost_at_blended_rate,
    cost_at_pool_rates,
    (revenue - cost_at_blended_rate) / nullif(revenue, 0)                                    as margin_at_blended_rate,
    (revenue - cost_at_pool_rates) / nullif(revenue, 0)                                      as margin_at_pool_rates,
    (cost_at_blended_rate - cost_at_pool_rates) / nullif(revenue, 0)                         as margin_points_moved,
    rank() over (order by (revenue - cost_at_blended_rate) / nullif(revenue, 0) desc)        as rank_at_blended_rate,
    rank() over (order by (revenue - cost_at_pool_rates) / nullif(revenue, 0) desc)          as rank_at_pool_rates,
    greatest(cost_at_pool_rates - cost_at_blended_rate, 0)                                   as cost_understated_by_blended_rate,
    greatest(cost_at_pool_rates - cost_at_blended_rate, 0) * (1 + {{ var('target_markup') }}) as price_at_target_understated
from f
