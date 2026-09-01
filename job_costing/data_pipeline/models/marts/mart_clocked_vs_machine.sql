-- Clocked hours against machine hours on the monitored cells, by cell and month
-- before the labor codes.

with clocked as (

    select work_center_id, date_trunc('month', clock_date) as month, sum(hours) as clocked_hours, count(*) as records
    from {{ ref('stg_erp__labor_transactions') }}
    where job_id is not null and labor_type <> 'indirect' and not after_codes
    group by 1, 2

),

machine as (

    select machine_id as work_center_id, date_trunc('month', interval_date) as month,
           sum(case when state = 'in_cycle' then hours else 0 end) as in_cycle_hours,
           sum(case when state = 'setup' then hours else 0 end) as setup_hours,
           sum(case when state = 'alarm' then hours else 0 end) as alarm_hours
    from {{ ref('stg_monitoring__machine_monitoring') }}
    where interval_date < cast('{{ var("labor_codes_date") }}' as date)
    group by 1, 2

)

select
    c.work_center_id,
    left(c.work_center_id, 3)                                        as work_center_group,
    c.month,
    c.clocked_hours,
    c.records,
    m.in_cycle_hours,
    m.setup_hours,
    m.alarm_hours,
    m.in_cycle_hours + m.setup_hours                                 as machine_active_hours,
    c.clocked_hours / nullif(m.in_cycle_hours + m.setup_hours, 0) - 1 as clocked_over_machine_share
from clocked c
join machine m using (work_center_id, month)
