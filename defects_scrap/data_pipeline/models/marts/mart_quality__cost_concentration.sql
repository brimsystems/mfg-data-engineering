-- Scrap and rework cost by part and customer.
-- Grain: one row per part number and month (a part belongs to one customer).

select
    production_month,
    part_number,
    customer,
    complexity,
    machine_type,
    count(*)                        as jobs,
    sum(quantity_inspected)         as quantity_inspected,
    sum(quantity_failed)            as quantity_failed,
    round(sum(scrap_cost), 2)       as scrap_cost,
    round(sum(revenue), 2)          as revenue
from {{ ref('mart_quality__defect_rates') }}
group by 1, 2, 3, 4, 5
