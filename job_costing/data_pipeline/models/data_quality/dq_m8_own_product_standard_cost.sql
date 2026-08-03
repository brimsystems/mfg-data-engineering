-- M8: own-product standard costs never revised. Every own product carries the
-- standard set at launch; shown against current cost.

select
    s.part_number,
    s.standard_cost,
    s.standard_cost_date,
    date_diff('month', s.standard_cost_date, cast('{{ var("end_date") }}' as date)) as months_since_standard,
    s.list_price,
    c.current_unit_cost,
    c.current_unit_cost / s.standard_cost - 1       as cost_vs_standard_share,
    c.current_unit_cost > s.list_price              as below_cost_at_list,
    1 - c.current_unit_cost / s.list_price          as margin_on_list_price,
    c.annual_volume
from {{ ref('stg_erp__own_product_standards') }} s
left join {{ ref('int_current_cost') }} c using (part_number)
