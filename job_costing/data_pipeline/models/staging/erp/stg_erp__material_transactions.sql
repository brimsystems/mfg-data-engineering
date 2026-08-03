with source as (

    select * from {{ source('erp', 'material_transactions') }}

)

select
    txn_id,
    job_id,
    material_spec,
    cast(quantity as double)                 as quantity,
    uom,
    cast(unit_cost as double)                as unit_cost,
    cast(quantity as double) * cast(unit_cost as double) as value,
    cast(issue_date as date)                 as issue_date,
    source
from source
