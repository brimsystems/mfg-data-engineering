with source as (

    select * from {{ source('remediation', 'standard_update_log') }}

)

select
    part_number,
    cast(op_seq as integer) as op_seq,
    work_center_id,
    cast(old_std_run_min as double) as old_std_run_min,
    cast(measured_run_min as double) as measured_run_min,
    cast(new_std_run_min as double) as new_std_run_min,
    cast(old_std_setup_hours as double) as old_std_setup_hours,
    cast(measured_setup_hours as double) as measured_setup_hours,
    cast(new_std_setup_hours as double) as new_std_setup_hours,
    reviewer_decision,
    reviewed_by,
    note,
    cast(effective_date as date) as effective_date
from source
