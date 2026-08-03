with source as (

    select * from {{ source('remediation', 'rate_pools') }}

)

select
    work_center_id,
    cast(effective_date as date) as effective_date,
    cast(labor_rate as double) as labor_rate,
    cast(burden_rate as double) as burden_rate,
    cast(attended_ratio as double) as attended_ratio,
    cast(labor_rate as double) * cast(attended_ratio as double) + cast(burden_rate as double) as pool_rate,
    basis
from source
