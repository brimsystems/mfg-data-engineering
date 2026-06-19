-- Defect rates by work order, with every dimension the diagnostic report and
-- the dashboard cut by. Grain: one row per work order.
--
-- Aggregate a defect rate as sum(quantity_failed) / sum(quantity_inspected),
-- never as the mean of the per-order rate.

with orders as (

    select * from {{ ref('int_quality__orders_enriched') }}

),

scrap as (

    select
        work_order_id,
        sum(total_scrap_cost)       as scrap_cost,
        sum(quantity_scrapped)      as quantity_scrapped,
        sum(quantity_reworked)      as quantity_reworked
    from {{ ref('int_quality__scrap_costs') }}
    group by 1

),

final as (

    select
        -- Keys
        o.work_order_id,
        o.inspection_id,

        -- Time
        o.order_date,
        o.job_start,
        o.job_end,
        o.production_day,
        date_trunc('month', o.production_day)                   as production_month,
        date_trunc('week', o.production_day)                    as production_week,
        extract('hour' from o.job_start)::integer               as job_start_hour,

        -- Part and order
        o.part_number,
        o.part_revision,
        o.customer,
        o.complexity,
        o.material_type,
        o.is_gauge_steel,
        o.nominal_thickness_in,
        o.requires_welding,
        o.is_rush,
        o.due_date,
        o.unit_price,

        -- Machine
        o.machine_id,
        o.machine_name,
        o.machine_type,
        o.machine_age_years,
        o.program_or_tool_set_id,
        o.setup_minutes,
        o.run_minutes,
        o.std_setup_min,
        o.setup_ratio_to_standard,

        -- Operator
        o.operator_id,
        o.operator_name,
        o.hire_date,
        o.cert_level,
        o.primary_machine_type,
        o.assigned_shift,
        o.shift_code,
        o.is_coverage,
        (o.hire_date >= o.record_start)                         as is_hired_in_period,
        o.jobs_in_log_before,
        o.prior_jobs_estimated,
        o.jobs_on_machine_type_before,
        o.hours_into_operator_day,

        -- Material lot
        o.lot_id,
        o.supplier,
        o.lot_cert_status,
        o.is_thickness_measured,
        o.thickness_deviation_pct,
        o.abs_thickness_deviation_pct,
        o.lot_age_days,

        -- Inspection result
        o.quantity_ordered,
        o.quantity_inspected,
        o.quantity_passed,
        o.quantity_failed,
        o.defect_rate,
        (o.quantity_failed > 0)                                 as defect_flag,
        o.defect_code,
        o.disposition,
        o.first_piece_failed,
        o.is_inspection_time_out_of_sequence,
        o.is_clock_entry_corrected,

        -- Cost and revenue
        coalesce(s.scrap_cost, 0)                               as scrap_cost,
        coalesce(s.quantity_scrapped, 0)                        as quantity_scrapped,
        coalesce(s.quantity_reworked, 0)                        as quantity_reworked,
        o.quantity_ordered - coalesce(s.quantity_scrapped, 0)   as quantity_shipped,
        round((o.quantity_ordered - coalesce(s.quantity_scrapped, 0)) * o.unit_price, 2)  as revenue,

        -- Finding dimensions
        o.run_position,
        (o.run_position = 1)                                    as is_first_run,
        o.has_first_piece_inspection,
        (o.hours_into_operator_day > 10)                        as is_past_tenth_hour,
        o.is_after_gauge_change,
        case
            when o.jobs_on_machine_type_before < 50  then 'under 50'
            when o.jobs_on_machine_type_before < 150 then '50 to 150'
            when o.jobs_on_machine_type_before < 300 then '150 to 300'
            else 'over 300'
        end                                                     as experience_band,
        case
            when o.lot_age_days is null then null
            when o.lot_age_days < 60    then 'under 60 days'
            when o.lot_age_days < 120   then '60 to 120 days'
            else 'over 120 days'
        end                                                     as lot_age_band,
        case
            when o.abs_thickness_deviation_pct is null then null
            when o.abs_thickness_deviation_pct < 1  then 'under 1%'
            when o.abs_thickness_deviation_pct < 2  then '1 to 2%'
            when o.abs_thickness_deviation_pct < 4  then '2 to 4%'
            else 'over 4%'
        end                                                     as thickness_deviation_band
    from orders o
    left join scrap s
        on o.work_order_id = s.work_order_id

)

select * from final
