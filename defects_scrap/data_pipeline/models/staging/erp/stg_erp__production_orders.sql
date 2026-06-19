-- ERP work orders. Grain: one row per work order.
--
-- Identifiers are cleaned from the fields as keyed:
--   part number   five formats (P-1234, P1234, p-1234, PART-1234, P 1234) to P-1234
--   operator      a name in the id field is resolved through the HR roster
--   lot id        four formats to LOT-1234; null where the lot was not scanned
--                 at job start, and left null
--   shift code    null on about 10% of orders; taken from the start time where
--                 that falls inside a shift window, otherwise left null

with source as (

    select * from {{ source('erp', 'production_orders') }}

),

roster as (

    select operator_id, operator_name from {{ source('hr', 'operators') }}

),

staged as (

    select
        s.work_order_id,
        'P-' || regexp_extract(s.part_number_raw, '(\d+)', 1)                    as part_number,
        s.part_number_raw,
        s.part_revision,
        s.customer,
        cast(s.quantity_ordered as integer)                                     as quantity_ordered,
        s.machine_id,
        coalesce(r.operator_id, s.operator_id_raw)                              as operator_id,
        s.operator_id_raw,
        coalesce(
            s.shift_code,
            case
                when cast(s.actual_start as timestamp)::time between '06:00:00' and '13:59:59' then 'Shift A'
                when cast(s.actual_start as timestamp)::time between '14:00:00' and '21:59:59' then 'Shift B'
            end
        )                                                                       as shift_code,
        case
            when s.lot_id_raw is null then null
            else 'LOT-' || regexp_replace(cast(s.lot_id_raw as varchar), '\D', '', 'g')
        end                                                                     as lot_id,
        cast(s.lot_id_raw as varchar)                                           as lot_id_raw,
        cast(s.order_date as date)                                              as order_date,
        cast(s.due_date as date)                                                as due_date,
        cast(s.rush_flag as boolean)                                            as is_rush,
        cast(s.scheduled_start as timestamp)                                    as scheduled_start,
        cast(s.actual_start as timestamp)                                       as actual_start,
        cast(s.actual_end as timestamp)                                         as actual_end,
        s.complexity,
        s.material_type,
        cast(s.requires_welding as boolean)                                     as requires_welding,
        cast(s.std_labor_hrs as double)                                         as std_labor_hrs
    from source s
    left join roster r
        on s.operator_id_raw = r.operator_name

)

select * from staged
