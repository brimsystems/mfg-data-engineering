-- QMS inspection records. Grain: one row per inspection kept.
--
-- A work order has one final inspection of the lot and, on most jobs, a
-- first-piece inspection. The QMS creates a second final inspection when a
-- session times out and the inspector submits again; the earliest entry per
-- work order is kept. The defect code is taken from the controlled vocabulary;
-- the code as typed is kept beside it.

with source as (

    select * from {{ source('qms', 'inspection_records') }}

),

staged as (

    select
        inspection_id,
        work_order_id,
        inspection_type,
        cast(inspection_date as timestamp)      as inspection_date,
        inspector_id,
        cast(quantity_inspected as integer)     as quantity_inspected,
        cast(quantity_passed as integer)        as quantity_passed,
        cast(quantity_failed as integer)        as quantity_failed,
        defect_code_clean                       as defect_code,
        defect_code_raw,
        disposition,
        notes,
        row_number() over (
            partition by work_order_id, inspection_type
            order by cast(regexp_extract(inspection_id, '(\d+)', 1) as integer)
        )                                       as entry_number
    from source

)

select * exclude (entry_number)
from staged
where entry_number = 1
