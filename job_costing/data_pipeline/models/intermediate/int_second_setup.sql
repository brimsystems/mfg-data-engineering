-- A second setup on an operation: the job was stopped for another job and set up
-- again when it resumed. On the monitored cells it is read from the machine feed: a
-- setup interval on the same job and program after its run had begun, with another
-- job in cycle on that machine in between. Operations whose machine time was split
-- across several open jobs are left out, since the split cannot place the setup.
-- Where the cell is not monitored and the labor codes exist, it is a setup record
-- clocked after a run record on the same operation.
-- Grain: job, work center.

with machine as (

    select job_id, machine_id, program_number, state, start_time, assigned_hours, split_flag
    from {{ ref('int_machine_interval_assignment') }}
    where job_id is not null

),

whole as (

    select job_id, machine_id, program_number
    from machine
    group by 1, 2, 3
    having not bool_or(split_flag)

),

first_cycle as (

    select m.job_id, m.machine_id, m.program_number, min(m.start_time) as run_began
    from machine m
    join whole w using (job_id, machine_id, program_number)
    where m.state = 'in_cycle'
    group by 1, 2, 3

),

later_setup as (

    select m.job_id, m.machine_id, m.start_time, m.assigned_hours, f.run_began
    from machine m
    join first_cycle f using (job_id, machine_id, program_number)
    where m.state = 'setup' and m.start_time > f.run_began

),

other_job_running as (

    select distinct machine_id, job_id, start_time
    from machine
    where state = 'in_cycle'

),

from_machine as (

    select s.job_id, s.machine_id as work_center_id,
           sum(s.assigned_hours) as second_setup_hours, min(s.start_time) as second_setup_at
    from later_setup s
    where exists (select 1 from other_job_running o
                  where o.machine_id = s.machine_id and o.job_id <> s.job_id
                    and o.start_time > s.run_began and o.start_time < s.start_time)
    group by 1, 2

),

clock as (

    select job_id, op_seq, work_center_id, labor_type, clock_on, hours
    from {{ ref('stg_erp__labor_transactions') }}
    where after_codes and job_id is not null and source = 'terminal' and labor_type in ('setup', 'run')

),

first_run as (

    select job_id, op_seq, work_center_id, min(clock_on) as run_began
    from clock
    where labor_type = 'run'
    group by 1, 2, 3

),

from_clock as (

    select c.job_id, c.work_center_id, sum(c.hours) as second_setup_hours, min(c.clock_on) as second_setup_at
    from clock c
    join first_run f using (job_id, op_seq, work_center_id)
    join {{ ref('stg_erp__work_centers') }} w using (work_center_id)
    where c.labor_type = 'setup' and c.clock_on > f.run_began and not w.monitored_flag
    group by 1, 2

)

select job_id, work_center_id, second_setup_hours, second_setup_at, 'machine' as source
from from_machine
union all
select job_id, work_center_id, second_setup_hours, second_setup_at, 'clock' as source
from from_clock
