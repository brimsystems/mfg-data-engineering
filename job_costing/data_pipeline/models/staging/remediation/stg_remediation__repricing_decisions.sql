with source as (

    select * from {{ source('remediation', 'repricing_decisions') }}

)

select
    part_number,
    customer_id,
    decision,
    cast(new_price as double)                as new_price,
    rationale,
    decided_by,
    cast(decision_date as date)              as decision_date
from source
