-- Reliability by machine. Grain: one row per machine.
-- MTBF is running hours per unplanned repair. Interval services are planned
-- work and are not failures, so they are left out of MTBF; the second measure,
-- mean running hours between repairs planned and unplanned, counts both.
-- MTTR is the mean downtime hours of an unplanned repair.
-- The interval service comes due repair_interval_days after the machine's last
-- repair of either kind; days_until_interval_service is counted from the end of
-- the record and is negative once the service is past due.

with running as (

    select machine_id, sum(run_minutes) / 60.0 as run_hours
    from {{ ref('mart_oee__machine_performance') }}
    group by 1

),

events as (

    select
        machine_id,
        count(*) filter (where is_unplanned_repair)                     as unplanned_repairs,
        count(*) filter (where is_interval_service)                     as interval_services,
        sum(downtime_hours) filter (where is_unplanned_repair)          as unplanned_repair_hours,
        sum(downtime_hours) filter (where is_interval_service)          as interval_service_hours,
        avg(downtime_hours) filter (where is_unplanned_repair)          as mttr_hours,
        max(event_date) filter (where is_repair)                        as last_repair_date
    from {{ ref('int_fct_maintenance_events') }}
    group by 1

),

machines as (

    select machine_id, machine_type, machine_age_years, is_aging_asset, repair_interval_days
    from {{ ref('int_dim_machines') }}

)

select
    m.machine_id,
    m.machine_type,
    m.machine_age_years,
    m.is_aging_asset,
    m.repair_interval_days,
    r.run_hours,
    coalesce(e.unplanned_repairs, 0)                                    as unplanned_repairs,
    coalesce(e.interval_services, 0)                                    as interval_services,
    coalesce(e.unplanned_repair_hours, 0)                               as unplanned_repair_hours,
    coalesce(e.interval_service_hours, 0)                               as interval_service_hours,
    r.run_hours / nullif(e.unplanned_repairs, 0)                        as mtbf_hours,
    r.run_hours / nullif(e.unplanned_repairs + e.interval_services, 0)  as hours_between_repairs_planned_and_unplanned,
    e.mttr_hours,
    e.last_repair_date,
    e.last_repair_date + m.repair_interval_days                         as interval_service_due_date,
    date_diff('day', date '{{ var("end_date") }}',
              e.last_repair_date + m.repair_interval_days)             as days_until_interval_service
from machines m
left join running r on r.machine_id = m.machine_id
left join events  e on e.machine_id = m.machine_id
order by m.machine_id
