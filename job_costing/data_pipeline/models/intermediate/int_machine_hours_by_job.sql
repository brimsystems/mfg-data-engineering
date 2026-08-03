-- Machine hours per job and work center from the assignment, with the
-- hours-weighted confidence. The hours the cleaned job cost uses on monitored cells.

select
    job_id,
    machine_id                                                   as work_center_id,
    sum(case when state = 'setup' then assigned_hours else 0 end)    as machine_setup_hours,
    sum(case when state = 'in_cycle' then assigned_hours else 0 end) as machine_run_hours,
    sum(case when state = 'alarm' then assigned_hours else 0 end)    as machine_alarm_hours,
    sum(case when state = 'idle' then assigned_hours else 0 end)     as machine_idle_hours,
    sum(assigned_hours)                                          as machine_hours,
    sum(assigned_hours * confidence) / nullif(sum(assigned_hours), 0) as assignment_confidence,
    bool_or(split_flag)                                          as any_split,
    min(start_time)                                              as first_activity,
    max(end_time)                                                as last_activity
from {{ ref('int_machine_interval_assignment') }}
where job_id is not null
group by 1, 2
