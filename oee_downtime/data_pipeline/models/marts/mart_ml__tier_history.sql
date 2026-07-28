-- The health indicator's rating and the two baselines' readings by machine and
-- day, with what followed on that machine in the next 7 days and the next 21:
-- an unplanned repair, an interval service, both or neither. Grain: one row per
-- machine and operating day (the highest rating of the day's shifts). Built
-- after scoring: it reads the tier history the scoring step writes.
-- A rating is read against what followed it in three exclusive parts: an
-- unplanned repair; an interval service and no repair; neither.

{{ config(tags=['after_scoring']) }}

with tiers as (

    select machine_id, cast(observation_date as date) as observation_date,
           model as indicator_rating, rules as rules_rating, calendar_pm as calendar_pm_rating
    from {{ source('ml', 'tier_history') }}

),

events as (

    select machine_id, event_date, is_unplanned_repair, is_interval_service
    from {{ ref('int_fct_maintenance_events') }}
    where is_repair

),

followed as (

    select
        t.machine_id,
        t.observation_date,
        coalesce(bool_or(e.is_unplanned_repair) filter (where e.event_date <= t.observation_date + 7), false)  as unplanned_repair_within_7d,
        coalesce(bool_or(e.is_interval_service) filter (where e.event_date <= t.observation_date + 7), false)  as interval_service_within_7d,
        coalesce(bool_or(e.is_unplanned_repair), false)                 as unplanned_repair_within_21d,
        coalesce(bool_or(e.is_interval_service), false)                 as interval_service_within_21d
    from tiers t
    left join events e
        on e.machine_id = t.machine_id
       and e.event_date >  t.observation_date
       and e.event_date <= t.observation_date + 21
    group by 1, 2

)

select
    {{ dbt_utils.generate_surrogate_key(['t.machine_id', 't.observation_date']) }} as machine_day_key,
    t.machine_id,
    t.observation_date,
    (t.observation_date >= date '{{ var("as_of_date") }}')              as in_scoring_quarter,
    (t.observation_date between date '{{ var("test_start_date") }}' and date '{{ var("test_end_date") }}') as in_test_period,
    t.indicator_rating,
    t.rules_rating,
    t.calendar_pm_rating,
    f.unplanned_repair_within_7d,
    f.interval_service_within_7d,
    f.unplanned_repair_within_21d,
    f.interval_service_within_21d
from tiers t
join followed f
    on f.machine_id = t.machine_id and f.observation_date = t.observation_date
order by t.machine_id, t.observation_date
