with source as (

    select * from {{ source('erp', 'vendors') }}

)

select
    vendor_id,
    name                                     as vendor_name,
    service_type,
    cast(minimum_charge as double)           as vendor_minimum_charge
from source
