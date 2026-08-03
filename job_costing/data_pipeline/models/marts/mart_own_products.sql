-- The fourteen own products: standard cost at launch, list price, current cost.

select
    m.part_number,
    p.description,
    p.material_spec,
    m.standard_cost,
    m.standard_cost_date,
    m.months_since_standard,
    m.list_price,
    m.current_unit_cost,
    m.cost_vs_standard_share,
    m.below_cost_at_list,
    m.margin_on_list_price,
    m.annual_volume,
    r.reviewed_by,
    r.review_week
from {{ ref('dq_m8_own_product_standard_cost') }} m
join {{ ref('stg_erp__part_master') }} p using (part_number)
left join {{ ref('stg_remediation__own_product_review') }} r using (part_number)
