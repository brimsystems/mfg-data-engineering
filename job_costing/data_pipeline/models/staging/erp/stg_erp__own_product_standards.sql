with source as (

    select * from {{ source('erp', 'own_product_standards') }}

)

select
    part_number,
    cast(standard_cost as double)            as standard_cost,
    cast(standard_cost_date as date)         as standard_cost_date,
    cast(list_price as double)               as list_price
from source
