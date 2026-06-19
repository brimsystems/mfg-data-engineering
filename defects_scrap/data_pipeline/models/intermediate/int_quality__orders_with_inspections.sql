-- Work orders with their job-log times and final inspection result.
-- Grain: one row per work order with a final inspection.
--
-- Defect rate is quantity failed over quantity inspected at final inspection.
-- First-piece results are not part of it; whether a first-piece inspection was
-- recorded is carried as a flag.

with orders as (

    select * from {{ ref('stg_erp__production_orders') }}

),

job_log as (

    select * from {{ ref('stg_mes__job_log') }}

),

final_inspection as (

    select * from {{ ref('stg_qms__inspection_records') }}
    where inspection_type = 'final'

),

first_piece as (

    select work_order_id, quantity_failed as first_piece_failed
    from {{ ref('stg_qms__inspection_records') }}
    where inspection_type = 'first_piece'

),

joined as (

    select
        o.work_order_id,
        i.inspection_id,
        o.part_number,
        o.part_revision,
        o.customer,
        o.machine_id,
        -- The job log is the record of who ran the job and when; the ERP start
        -- is entered later on some orders.
        j.operator_id,
        o.shift_code,
        o.lot_id,
        o.complexity,
        o.material_type,
        o.requires_welding,
        o.is_rush,
        o.order_date,
        o.due_date,
        j.job_start,
        j.job_end,
        j.setup_minutes,
        j.run_minutes,
        j.program_or_tool_set_id,
        j.is_clock_entry_corrected,
        o.actual_start                                                  as erp_actual_start,
        datediff('minute', j.job_start, o.actual_start)                 as erp_start_lag_minutes,
        i.inspection_date,
        o.quantity_ordered,
        i.quantity_inspected,
        i.quantity_passed,
        i.quantity_failed,
        case when i.quantity_inspected = 0 then null
             else cast(i.quantity_failed as double) / i.quantity_inspected end  as defect_rate,
        i.defect_code,
        i.disposition,
        (f.work_order_id is not null)                                   as has_first_piece_inspection,
        coalesce(f.first_piece_failed, 0) > 0                           as first_piece_failed,
        -- An inspection time before the job started, or more than eight hours
        -- after it ended, was filled in after the fact.
        (i.inspection_date < j.job_start
         or i.inspection_date > j.job_end + interval 8 hour)            as is_inspection_time_out_of_sequence
    from orders o
    inner join job_log j
        on o.work_order_id = j.work_order_id
    inner join final_inspection i
        on o.work_order_id = i.work_order_id
    left join first_piece f
        on o.work_order_id = f.work_order_id

)

select * from joined
