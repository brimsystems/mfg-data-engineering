with source as (

    select * from {{ source('remediation', 'attended_ratios') }}

)

select
    work_center_id,
    cast(attended_ratio as double) as attended_ratio,
    observation_note,
    observed_by,
    cast(observation_week as integer) as observation_week
from source
