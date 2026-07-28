-- The scoring quarter's unplanned failures. Grain: one row per unplanned repair
-- opened from the as-of date to the end of the record.
-- Beside each failure: the days since the machine's last repair (unplanned or
-- interval service) and whether that had reached the machine's repair interval,
-- the health indicator's rating on each of the 7 days before the repair opened,
-- and the rules baseline's reading over the same days. A failure is warned
-- before when the indicator read CRITICAL on at least one of those days.
-- Built after scoring: it reads the tier history the scoring step writes.

{{ config(tags=['after_scoring']) }}

with failures as (

    select maintenance_id, machine_id, machine_type, event_date as failure_date,
           failure_code, downtime_hours
    from {{ ref('int_fct_maintenance_events') }}
    where is_unplanned_repair
      and event_date >= date '{{ var("as_of_date") }}'

),

repairs as (

    select machine_id, event_date as repair_date, maintenance_type
    from {{ ref('int_fct_maintenance_events') }}
    where is_repair

),

machines as (

    select machine_id, repair_interval_days from {{ ref('int_dim_machines') }}

),

tiers as (

    select machine_id, cast(observation_date as date) as observation_date,
           model as indicator_rating, rules as rules_rating, calendar_pm as calendar_pm_rating
    from {{ source('ml', 'tier_history') }}

),

last_repair as (

    select
        f.maintenance_id,
        max(r.repair_date)                                              as last_repair_date,
        arg_max(r.maintenance_type, r.repair_date)                      as last_repair_type
    from failures f
    left join repairs r
        on r.machine_id = f.machine_id and r.repair_date < f.failure_date
    group by 1

),

before as (

    select
        f.maintenance_id,
        {% for d in range(1, 8) %}
        max(t.indicator_rating) filter (where t.observation_date = f.failure_date - {{ d }}) as indicator_rating_{{ d }}d_before,
        {% endfor %}
        count(*) filter (where t.indicator_rating = 'CRITICAL')         as indicator_critical_days_before,
        count(*) filter (where t.rules_rating = 'CRITICAL')             as rules_critical_days_before,
        count(*) filter (where t.calendar_pm_rating = 'CRITICAL')       as calendar_pm_critical_days_before
    from failures f
    left join tiers t
        on t.machine_id = f.machine_id
       and t.observation_date >= f.failure_date - 7
       and t.observation_date <  f.failure_date
    group by 1

),

-- The 21-day reading: CRITICAL or ELEVATED on at least one of the 21 days before.
before_21 as (

    select
        f.maintenance_id,
        count(*) filter (where t.indicator_rating in ('CRITICAL', 'ELEVATED'))   as indicator_days,
        count(*) filter (where t.rules_rating in ('CRITICAL', 'ELEVATED'))       as rules_days,
        count(*) filter (where t.calendar_pm_rating in ('CRITICAL', 'ELEVATED')) as calendar_pm_days
    from failures f
    left join tiers t
        on t.machine_id = f.machine_id
       and t.observation_date >= f.failure_date - 21
       and t.observation_date <  f.failure_date
    group by 1

)

select
    f.maintenance_id,
    f.machine_id,
    f.machine_type,
    f.failure_date,
    f.failure_code,
    f.downtime_hours,
    m.repair_interval_days,
    l.last_repair_date,
    l.last_repair_type,
    date_diff('day', l.last_repair_date, f.failure_date)                as days_since_last_repair,
    coalesce(date_diff('day', l.last_repair_date, f.failure_date) >= m.repair_interval_days, false)
                                                                        as interval_reached_before_failure,
    {% for d in range(1, 8) %}
    b.indicator_rating_{{ d }}d_before,
    {% endfor %}
    b.indicator_critical_days_before,
    (b.indicator_critical_days_before > 0)                              as warned_before,
    b.rules_critical_days_before,
    (b.rules_critical_days_before > 0)                                  as rules_warned_before,
    (b.calendar_pm_critical_days_before > 0)                            as calendar_pm_warned_before,
    (b21.indicator_days > 0)                                            as warned_before_21d,
    (b21.rules_days > 0)                                                as rules_warned_before_21d,
    (b21.calendar_pm_days > 0)                                          as calendar_pm_warned_before_21d
from failures f
left join machines m    on m.machine_id = f.machine_id
left join last_repair l on l.maintenance_id = f.maintenance_id
left join before b      on b.maintenance_id = f.maintenance_id
left join before_21 b21 on b21.maintenance_id = f.maintenance_id
order by f.failure_date, f.machine_id
