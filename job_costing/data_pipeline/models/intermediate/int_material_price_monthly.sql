-- The price actually paid for each material spec by month, from the issues
-- themselves (the ERP has no price table). Grain: material spec and month.

select
    material_spec,
    uom,
    date_trunc('month', issue_date)          as month,
    median(unit_cost)                        as unit_cost,
    count(*)                                 as issues
from {{ ref('stg_erp__material_transactions') }}
where quantity > 0
group by 1, 2, 3
