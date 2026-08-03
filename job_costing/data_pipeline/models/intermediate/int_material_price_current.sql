-- Today's price per material spec: the median of the last three months issued.

with recent as (

    select material_spec, uom, unit_cost, issues,
           row_number() over (partition by material_spec order by month desc) as rn
    from {{ ref('int_material_price_monthly') }}

)

select material_spec, uom, sum(unit_cost * issues) / sum(issues) as unit_cost_current
from recent
where rn <= 3
group by 1, 2
