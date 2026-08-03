with source as (

    select * from {{ source('erp', 'jobs') }}

)

select
    job_id,
    part_number,
    revision,
    customer_id,
    cast(quantity as integer)                as quantity,
    job_type,
    quote_id,
    cast(release_date as date)               as release_date,
    cast(due_date as date)                   as due_date,
    cast(completed_date as date)             as completed_date,
    status,
    cast(price as double)                    as price,
    cast(est_material as double)             as est_material,
    cast(est_setup_hours as double)          as est_setup_hours,
    cast(est_run_hours as double)            as est_run_hours,
    cast(est_outside as double)              as est_outside,
    cast(est_total_cost as double)           as est_total_cost,
    cast(actual_material as double)          as actual_material,
    cast(actual_labor_hours as double)       as actual_labor_hours,
    cast(actual_labor_cost as double)        as actual_labor_cost,
    cast(actual_outside as double)           as actual_outside,
    cast(actual_scrap_qty as integer)        as actual_scrap_qty,
    cast(actual_total_cost as double)        as actual_total_cost,
    cast(release_date as date) >= cast('{{ var("estimate_to_job_date") }}' as date) as released_after_config,
    cast(release_date as date) >= cast('{{ var("engagement_start") }}' as date) as in_engagement,
    case when cast(release_date as date) >= cast('{{ var("engagement_start") }}' as date)
         then least(12, (date_diff('day', cast('{{ var("engagement_start") }}' as date), cast(release_date as date)) // 7) + 1) end as engagement_week
from source
