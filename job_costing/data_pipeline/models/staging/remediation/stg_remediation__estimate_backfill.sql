with source as (

    select * from {{ source('remediation', 'estimate_backfill') }}

)

select
    job_id,
    quote_id,
    method,
    cast(match_confidence as double) as match_confidence,
    cast(est_material as double) as est_material,
    cast(est_setup_hours as double) as est_setup_hours,
    cast(est_run_hours as double) as est_run_hours,
    cast(est_outside as double) as est_outside,
    cast(est_total_cost as double) as est_total_cost,
    cast(material_price_date as date) as material_price_date
from source
