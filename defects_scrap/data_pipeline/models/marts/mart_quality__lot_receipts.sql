-- Material lots as received. Grain: one row per lot.
--
-- Thickness deviation is the micrometer check at receiving against nominal;
-- it is null on lots where the check was not recorded.

select
    lot_id,
    supplier,
    material_type,
    (material_type like '%ga Steel')            as is_gauge_steel,
    receipt_date,
    date_trunc('month', receipt_date)           as receipt_month,
    cert_status,
    is_thickness_measured,
    nominal_thickness_in,
    measured_thickness_in,
    thickness_deviation_pct,
    abs(thickness_deviation_pct)                as abs_thickness_deviation_pct,
    case
        when thickness_deviation_pct is null then null
        when abs(thickness_deviation_pct) < 1 then 'under 1%'
        when abs(thickness_deviation_pct) < 2 then '1 to 2%'
        when abs(thickness_deviation_pct) < 4 then '2 to 4%'
        else 'over 4%'
    end                                         as thickness_deviation_band
from {{ ref('stg_materials__lots') }}
