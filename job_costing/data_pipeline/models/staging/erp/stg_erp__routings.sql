with source as (

    select * from {{ source('erp', 'routings') }}

)

select
    part_number,
    revision,
    cast(op_seq as integer)                  as op_seq,
    work_center_id,
    cast(std_setup_hours as double)          as std_setup_hours,
    cast(std_run_min_per_piece as double)    as std_run_min_per_piece,
    program_number,
    cast(last_updated as date)               as last_updated
from source
