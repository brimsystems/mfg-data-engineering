-- HR operator roster. Grain: one row per operator employed in the period.

select
    operator_id,
    operator_name,
    cast(hire_date as date)     as hire_date,
    primary_machine_type,
    secondary_machine_type,
    shift                       as assigned_shift,
    cert_level
from {{ source('hr', 'operators') }}
