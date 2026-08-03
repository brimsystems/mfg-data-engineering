with source as (

    select * from {{ source('erp', 'labor_transactions') }}

)

select
    txn_id,
    job_id,
    cast(op_seq as integer)                  as op_seq,
    work_center_id,
    employee_id,
    cast(clock_on as timestamp)              as clock_on,
    cast(clock_off as timestamp)             as clock_off,
    type                                     as labor_type,
    source,
    cast(hours as double)                    as hours,
    cast(clock_on as date)                   as clock_date,
    cast(clock_on as timestamp) >= cast('{{ var("labor_codes_date") }}' as timestamp) as after_codes
from source
