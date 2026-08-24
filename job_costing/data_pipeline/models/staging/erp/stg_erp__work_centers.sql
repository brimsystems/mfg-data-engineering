with source as (

    select * from {{ source('erp', 'work_centers') }}

)

select
    work_center_id,
    type                                     as work_center_type,
    left(work_center_id, 3)                  as work_center_group,
    cast(monitored_flag as boolean)          as monitored_flag,
    machine_id,
    cast(install_year as integer)            as install_year,
    left(work_center_id, 3) in ('SAW', 'MDP', 'DBR', 'INS', 'ASM') as is_secondary
from source
