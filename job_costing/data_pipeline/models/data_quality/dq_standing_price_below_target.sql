-- Standing prices not repriced. Repeat parts whose standing price sits below
-- current cost plus the target markup.

select
    part_number,
    part_family,
    customer_id,
    material_spec,
    first_quote_date,
    standing_price,
    current_unit_cost,
    target_price,
    markup_on_current_cost,
    margin_on_price,
    annual_volume,
    gap_to_target_annual,
    current_unit_cost > standing_price              as below_cost,
    moved_material,
    moved_rate,
    moved_standard,
    moved_outside
from {{ ref('int_current_cost') }}
where part_type = 'repeat'
  and standing_price < target_price
