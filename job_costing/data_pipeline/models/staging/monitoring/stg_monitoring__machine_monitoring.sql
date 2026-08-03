with source as (

    select * from {{ source('monitoring', 'machine_monitoring') }}

)

select
    interval_id,
    machine_id,
    cast(start_time as timestamp)            as start_time,
    cast(end_time as timestamp)              as end_time,
    state,
    program_number,
    cast(cycle_count as integer)             as cycle_count,
    assigned_job_id,
    date_diff('second', cast(start_time as timestamp), cast(end_time as timestamp)) / 3600.0 as hours,
    cast(start_time as date)                 as interval_date
from source
