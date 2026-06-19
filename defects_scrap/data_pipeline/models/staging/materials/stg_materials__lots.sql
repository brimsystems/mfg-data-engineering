-- Materials lot receipts. Grain: one row per lot received.
--
-- The lot id is keyed in several formats (LOT-1234, LOT1234, 1234, L-1234) and
-- is normalized to LOT-1234. The micrometer check at receiving is not recorded
-- on every lot; thickness deviation is null where it was not.

select
    'LOT-' || regexp_replace(cast(lot_id_raw as varchar), '\D', '', 'g')   as lot_id,
    cast(lot_id_raw as varchar)                 as lot_id_raw,
    supplier,
    material_type,
    cast(receipt_date as date)                  as receipt_date,
    cert_status,
    cast(quantity_lbs as integer)               as quantity_lbs,
    cast(unit_cost_per_lb as double)            as unit_cost_per_lb,
    cast(nominal_thickness_in as double)        as nominal_thickness_in,
    cast(measured_thickness_in as double)       as measured_thickness_in,
    cast(thickness_deviation_pct as double)     as thickness_deviation_pct,
    (measured_thickness_in is not null)         as is_thickness_measured
from {{ source('materials', 'material_lots') }}
