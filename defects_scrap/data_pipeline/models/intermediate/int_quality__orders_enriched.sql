-- Work orders enriched from every system. Grain: one row per work order.
--
--   ERP        part master (complexity, standard setup, unit price, release
--              date), revision on the order, rush flag
--   MES        machine register; position of the job in the machine's sequence
--              and in the operator's day, from the job log
--   Materials  the lot scanned at job start: supplier, cert status, thickness
--              deviation at receiving, days since receipt
--   HR         the operator's hire date and machine types
--
-- Derived here, once, for every mart:
--   run position        first, second or later work order on the drawing
--                       revision. A revision A drawing released before the
--                       record starts is treated as already run.
--   experience          jobs the operator had run on the machine type before
--                       this one: the job-log count, plus prior jobs estimated
--                       from the HR hire date for operators hired before the
--                       log starts (jobs_per_operator_year on the primary
--                       machine type, a share of that on the secondary).
--   hours into the day  job start minus the operator's first job start of the
--                       day. An operator's day begins with the first job after
--                       a break of eight hours or more, so a shift that runs
--                       past midnight stays one day.
--   gauge change        the job before on the same machine ran a different
--                       material thickness.

with spine as (

    select * from {{ ref('int_quality__orders_with_inspections') }}

),

record as (

    select min(order_date) as record_start, min(cast(job_start as date)) as log_start
    from spine

),

parts as (

    select * from {{ ref('stg_erp__part_catalog') }}

),

machines as (

    select * from {{ ref('stg_mes__machines') }}

),

operators as (

    select * from {{ ref('stg_hr__operators') }}

),

lots as (

    select * from {{ ref('stg_materials__lots') }}

),

material_thickness as (

    select material_type, max(nominal_thickness_in) as nominal_thickness_in
    from lots
    group by 1

),

joined as (

    select
        s.*,
        p.std_setup_min,
        p.unit_price,
        p.released_date,
        m.machine_name,
        m.machine_type,
        m.machine_age_years,
        op.operator_name,
        op.hire_date,
        op.cert_level,
        op.primary_machine_type,
        op.secondary_machine_type,
        op.assigned_shift,
        l.supplier,
        l.cert_status                                   as lot_cert_status,
        l.receipt_date                                  as lot_receipt_date,
        l.is_thickness_measured,
        l.thickness_deviation_pct,
        abs(l.thickness_deviation_pct)                  as abs_thickness_deviation_pct,
        datediff('day', l.receipt_date, cast(s.job_start as date))  as lot_age_days,
        t.nominal_thickness_in,
        (s.material_type like '%ga Steel')              as is_gauge_steel,
        r.record_start,
        r.log_start
    from spine s
    cross join record r
    left join parts p               on s.part_number = p.part_number
    left join machines m            on s.machine_id = m.machine_id
    left join operators op          on s.operator_id = op.operator_id
    left join lots l                on s.lot_id = l.lot_id
    left join material_thickness t  on s.material_type = t.material_type

),

sequenced as (

    select
        *,
        row_number() over (
            partition by part_number, part_revision order by job_start, work_order_id
        )                                                               as revision_run_number,
        row_number() over (
            partition by operator_id, machine_type order by job_start, work_order_id
        ) - 1                                                           as jobs_in_log_before,
        greatest(0, datediff('day', hire_date, log_start)) / 365.25     as years_before_log,
        cast(job_start - interval 2 hour as date)                       as production_day,
        lag(job_end) over (
            partition by operator_id order by job_start, work_order_id
        )                                                               as operator_previous_job_end,
        lag(nominal_thickness_in) over (
            partition by machine_id order by job_start, work_order_id
        )                                                               as previous_thickness_in
    from joined

),

operator_days as (

    select
        *,
        sum(case when operator_previous_job_end is null
                   or job_start > operator_previous_job_end + interval 8 hour then 1 else 0 end) over (
            partition by operator_id order by job_start, work_order_id
            rows between unbounded preceding and current row
        )                                                               as operator_day_number
    from sequenced

),

final as (

    select
        * exclude (revision_run_number, jobs_in_log_before, years_before_log, operator_previous_job_end),

        -- Run position on the drawing revision
        case
            when part_revision = 'A' and released_date < record_start then 3
            else least(revision_run_number, 3)
        end                                                             as run_position,

        -- Experience on the machine type at job start
        jobs_in_log_before,
        round(years_before_log * {{ var('jobs_per_operator_year') }} * case
            when machine_type = primary_machine_type then 1.0
            when machine_type = secondary_machine_type then {{ var('secondary_type_prior_share') }}
            else 0.0
        end, 1)                                                         as prior_jobs_estimated,
        jobs_in_log_before + years_before_log * {{ var('jobs_per_operator_year') }} * case
            when machine_type = primary_machine_type then 1.0
            when machine_type = secondary_machine_type then {{ var('secondary_type_prior_share') }}
            else 0.0
        end                                                             as jobs_on_machine_type_before,
        (machine_type <> primary_machine_type)                          as is_coverage,

        -- Position in the operator's day
        datediff('second',
                 min(job_start) over (partition by operator_id, operator_day_number),
                 job_start) / 3600.0                                    as hours_into_operator_day,

        -- Position in the machine's sequence
        (previous_thickness_in is not null
         and previous_thickness_in <> nominal_thickness_in)             as is_after_gauge_change,

        setup_minutes / nullif(std_setup_min, 0)                        as setup_ratio_to_standard
    from operator_days

)

select * from final
