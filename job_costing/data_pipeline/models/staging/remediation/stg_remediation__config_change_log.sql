with source as (

    select * from {{ source('remediation', 'config_change_log') }}

)

select
    change,
    module,
    cast(effective_date as date) as effective_date,
    changed_by,
    cast(engagement_week as integer) as engagement_week
from source
