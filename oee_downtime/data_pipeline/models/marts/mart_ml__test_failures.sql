-- The held-out test period's unplanned failures. Grain: one row per unplanned
-- repair opened in the test period. Beside each failure, for the health
-- indicator and the two baselines: whether the source read CRITICAL on at least
-- one of the 7 days before the repair opened, and CRITICAL or ELEVATED on at
-- least one of the 21 days before. Built after scoring, the same way as the
-- scoring quarter's failures.

{{ config(tags=['after_scoring']) }}

with failures as (

    select maintenance_id, machine_id, machine_type, event_date as failure_date,
           failure_code, downtime_hours
    from {{ ref('int_fct_maintenance_events') }}
    where is_unplanned_repair
      and event_date between date '{{ var("test_start_date") }}' and date '{{ var("test_end_date") }}'

),

tiers as (

    select machine_id, cast(observation_date as date) as observation_date,
           model as indicator_rating, rules as rules_rating, calendar_pm as calendar_pm_rating
    from {{ source('ml', 'tier_history') }}

),

before as (

    select
        f.maintenance_id,
        count(*) filter (where t.observation_date >= f.failure_date - 7 and t.indicator_rating = 'CRITICAL')    as indicator_7,
        count(*) filter (where t.observation_date >= f.failure_date - 7 and t.rules_rating = 'CRITICAL')        as rules_7,
        count(*) filter (where t.observation_date >= f.failure_date - 7 and t.calendar_pm_rating = 'CRITICAL')  as calendar_pm_7,
        count(*) filter (where t.indicator_rating in ('CRITICAL', 'ELEVATED'))                                  as indicator_21,
        count(*) filter (where t.rules_rating in ('CRITICAL', 'ELEVATED'))                                      as rules_21,
        count(*) filter (where t.calendar_pm_rating in ('CRITICAL', 'ELEVATED'))                                as calendar_pm_21
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
    (b.indicator_7 > 0)                                                 as warned_before,
    (b.rules_7 > 0)                                                     as rules_warned_before,
    (b.calendar_pm_7 > 0)                                               as calendar_pm_warned_before,
    (b.indicator_21 > 0)                                                as warned_before_21d,
    (b.rules_21 > 0)                                                    as rules_warned_before_21d,
    (b.calendar_pm_21 > 0)                                              as calendar_pm_warned_before_21d
from failures f
left join before b on b.maintenance_id = f.maintenance_id
order by f.failure_date, f.machine_id
