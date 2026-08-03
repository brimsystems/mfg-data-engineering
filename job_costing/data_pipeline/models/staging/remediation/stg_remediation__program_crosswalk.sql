with source as (

    select * from {{ source('remediation', 'program_crosswalk') }}

)

select
    program_number,
    machine_id,
    part_number,
    revision,
    method,
    resolved_by,
    cast(confidence as double) as confidence,
    status
from source
