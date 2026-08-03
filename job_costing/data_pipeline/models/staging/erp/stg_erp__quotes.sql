with source as (

    select * from {{ source('erp', 'quotes') }}

)

select
    quote_id,
    cast(line as integer)                    as line,
    cast(break_seq as integer)               as break_seq,
    part_number,
    revision,
    customer_id,
    cast(quantity as integer)                as quantity,
    estimator_id,
    cast(quote_date as date)                 as quote_date,
    estimate_basis,
    cast(est_material as double)             as est_material,
    cast(est_setup_hours as double)          as est_setup_hours,
    cast(est_run_hours as double)            as est_run_hours,
    cast(est_outside as double)              as est_outside,
    cast(est_total_cost as double)           as est_total_cost,
    cast(quoted_price as double)             as quoted_price,
    status,
    won_job_id
from source
