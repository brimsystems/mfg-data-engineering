with source as (

    select * from {{ source('remediation', 'own_product_review') }}

)

select
    part_number,
    reviewed_by,
    cast(review_week as integer)             as review_week
from source
