with source as (

    select * from {{ source('remediation', 'engagement_actions') }}

)

select
    action_id,
    action,
    decision,
    decided_by,
    cast(engagement_week as integer) as engagement_week,
    cast(decision_date as date)      as decision_date,
    scope,
    reason
from source
