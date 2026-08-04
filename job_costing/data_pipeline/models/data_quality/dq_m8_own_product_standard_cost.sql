-- M8: own-product standard costs never revised. Every own product on the part
-- master carries the standard cost set when it was launched (its first-quote date)
-- and never revised; shown against current cost.

select
    p.part_number,
    p.standard_cost,
    p.first_quote_date                              as standard_cost_date,
    date_diff('month', p.first_quote_date, cast('{{ var("end_date") }}' as date)) as months_since_standard,
    p.list_price,
    c.current_unit_cost,
    c.current_unit_cost / p.standard_cost - 1       as cost_vs_standard_share,
    c.current_unit_cost > p.list_price              as below_cost_at_list,
    1 - c.current_unit_cost / p.list_price          as margin_on_list_price,
    c.annual_volume
from {{ ref('stg_erp__part_master') }} p
left join {{ ref('int_current_cost') }} c using (part_number)
where p.own_product_flag
