with source as (

    select * from {{ source('remediation', 'po_attribution') }}

)

select
    po_id,
    job_id,
    method,
    cast(confidence as double) as confidence,
    confirmed_by,
    status
from source
