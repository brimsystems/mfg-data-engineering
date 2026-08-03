with source as (

    select * from {{ source('remediation', 'interview_log') }}

)

select
    role,
    cast(interview_date as date) as interview_date,
    topic,
    consulted_on
from source
