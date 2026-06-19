-- ERP part master. Grain: one row per part number.

select
    part_number,
    customer,
    material_type,
    complexity,
    primary_machine,
    cast(std_setup_min as double)       as std_setup_min,
    cast(std_labor_hrs as double)       as std_labor_hrs,
    cast(unit_price as double)          as unit_price,
    cast(requires_welding as boolean)   as requires_welding,
    cast(released_date as date)         as released_date,
    current_revision,
    cast(revision_date as date)         as revision_date
from {{ source('erp', 'part_catalog') }}
