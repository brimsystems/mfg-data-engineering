with source as (

    select * from {{ source('erp', 'scrap_rework') }}

)

select
    event_id,
    job_id,
    cast(op_seq as integer)                  as op_seq,
    type                                     as event_type,
    cast(quantity as integer)                as quantity,
    reason_code,
    reported_by,
    cast(event_date as date)                 as event_date,
    cast(event_date as date) >= cast('{{ var("scrap_reason_date") }}' as date) as after_config
from source
