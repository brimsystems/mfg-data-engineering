with source as (

    select * from {{ source('erp', 'part_master') }}

)

select
    part_number,
    revision,
    description,
    material_spec,
    stock_form,
    part_family,
    customer_id,
    status,
    cast(first_quote_date as date)           as first_quote_date,
    cast(standing_price as double)           as standing_price,
    cast(standing_price_date as date)        as standing_price_date,
    cast(own_product_flag as boolean)        as own_product_flag,
    cast(list_price as double)               as list_price,
    case when own_product_flag then 'own_product'
         when part_number like 'P-%' then 'repeat' else 'new' end as part_type
from source
