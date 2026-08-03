with source as (

    select * from {{ source('erp', 'work_center_rates') }}

)

select
    work_center_id,
    cast(effective_date as date)             as effective_date,
    cast(labor_rate as double)               as labor_rate,
    cast(burden_rate as double)              as burden_rate,
    cast(labor_rate as double) + cast(burden_rate as double) as blended_rate,
    cast(attended_ratio as double)           as attended_ratio
from source
