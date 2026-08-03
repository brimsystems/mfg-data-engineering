with source as (

    select * from {{ source('remediation', 'config_gap_list') }}

)

select
    module,
    setting,
    as_found,
    gap,
    resolved_by
from source
