-- MES machine register. Grain: one row per machine.

select
    machine_id,
    machine_name,
    machine_type,
    cast(age_years as integer)  as machine_age_years,
    location
from {{ source('mes', 'machines') }}
