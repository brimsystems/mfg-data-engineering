-- Rework recorded as run time. Rework events logged before the rework code
-- existed: where the hours went to the catch-all operation 999 they can be seen;
-- everywhere else they posted as production on the operation and cannot be
-- separated from it. Grain: one row per rework event.

with events as (

    select e.event_id, e.job_id, e.op_seq, e.quantity, e.event_date, e.reported_by
    from {{ ref('stg_erp__scrap_rework') }} e
    where e.event_type = 'rework' and e.job_id is not null and not e.after_config

),

catch_all as (

    select job_id, clock_date, sum(hours) as hours_on_999
    from {{ ref('stg_erp__labor_transactions') }}
    where op_seq = 999
    group by 1, 2

),

same_day as (

    select job_id, op_seq, clock_date, sum(hours) as run_hours_on_operation, count(*) as run_records
    from {{ ref('stg_erp__labor_transactions') }}
    where labor_type = 'run' and op_seq <> 999
    group by 1, 2, 3

)

select
    e.event_id,
    e.job_id,
    e.op_seq,
    e.quantity,
    e.event_date,
    e.reported_by,
    c.hours_on_999,
    s.run_hours_on_operation,
    s.run_records,
    case when c.hours_on_999 is not null then 'hours posted as run on catch-all operation 999'
         else 'no rework record; hours sit in the operation''s run time' end as evidence,
    case when c.hours_on_999 is not null then 0.95 else 0.9 end as confidence
from events e
left join catch_all c on c.job_id = e.job_id and c.clock_date = e.event_date
left join same_day s on s.job_id = e.job_id and s.op_seq = e.op_seq and s.clock_date = e.event_date
