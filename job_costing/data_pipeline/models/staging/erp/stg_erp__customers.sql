with source as (

    select * from {{ source('erp', 'customers') }}

)

select
    customer_id,
    name                                     as customer_name,
    industry,
    terms,
    cast(change_order_count_12m as integer)  as change_order_count_12m,
    cast(expedite_count_12m as integer)      as expedite_count_12m
from source
