with source as (

    select * from {{ source('erp', 'outside_processing') }}

)

select
    po_id,
    cast(line as integer)                    as line,
    vendor_id,
    service_type,
    job_id,
    gl_account,
    description,
    cast(quantity as integer)                as quantity,
    cast(unit_price as double)               as unit_price,
    cast(order_date as date)                 as order_date,
    cast(receipt_date as date)               as receipt_date,
    cast(invoice_amount as double)           as invoice_amount,
    -- the part number typed into the description, where the buyer typed one
    regexp_extract(description, '((?:P|N|BC)-[0-9]+)', 1) as description_part_number,
    cast(order_date as date) >= cast('{{ var("po_job_required_date") }}' as date) as after_config
from source
