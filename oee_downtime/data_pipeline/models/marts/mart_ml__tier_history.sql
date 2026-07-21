-- The health indicator's rating and the rules baseline's reading by machine and
-- day, with what followed on that machine in the next 7 days: an unplanned
-- repair, an interval service, both or neither. Grain: one row per machine and
-- operating day. Built after scoring: it reads the tier history the scoring
-- step writes.

{{ config(tags=['after_scoring']) }}

with tiers as (

    select machine_id, cast(observation_date as date) as observation_date,
           model as indicator_rating, rules as rules_rating
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
        coalesce(bool_or(e.is_unplanned_repair), false)                 as unplanned_repair_within_7d,
        coalesce(bool_or(e.is_interval_service), false)                 as interval_service_within_7d
    from tiers t
    left join events e
        on e.machine_id = t.machine_id
       and e.event_date >  t.observation_date
       and e.event_date <= t.observation_date + 7
    group by 1, 2

)

select
    {{ dbt_utils.generate_surrogate_key(['t.machine_id', 't.observation_date']) }} as machine_day_key,
    t.machine_id,
    t.observation_date,
    (t.observation_date >= date '{{ var("as_of_date") }}')              as in_scoring_quarter,
    t.indicator_rating,
    t.rules_rating,
    f.unplanned_repair_within_7d,
    f.interval_service_within_7d
from tiers t
join followed f
    on f.machine_id = t.machine_id and f.observation_date = t.observation_date
order by t.machine_id, t.observation_date
