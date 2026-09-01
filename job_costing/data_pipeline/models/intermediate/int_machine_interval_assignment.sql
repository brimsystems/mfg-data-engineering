-- Machine time assigned to jobs. After the monitoring feed was tied to the ERP the
-- job number rides on the interval. Before that: program number to part through
-- the crosswalk, then part and date to the jobs open for it. A program shared by
-- several parts is settled by which of those parts had a job open on the machine's
-- cell that day. When more than one job qualifies, the interval is split by job
-- quantity and flagged. Grain: interval, job (a split interval has one row per job).

with intervals as (

    select interval_id, machine_id, left(machine_id, 3) as work_center_group,
           start_time, end_time, state, program_number, cycle_count, assigned_job_id, hours, interval_date
    from {{ ref('stg_monitoring__machine_monitoring') }}
    where state in ('setup', 'in_cycle', 'alarm')
       or (state = 'idle' and program_number is not null)   -- idle inside an operation: loading, inspection, a tool change

),

crosswalk as (

    select program_number, part_number, confidence,
           method = 'routing match' as unique_program
    from {{ ref('stg_remediation__program_crosswalk') }}
    where status = 'resolved'

),

unresolved_pairs as (

    select program_number, machine_id
    from {{ ref('stg_remediation__program_crosswalk') }}
    where status = 'unresolved'

),

erp_assigned as (

    select i.*, i.assigned_job_id as job_id, 1.0 as share, 1.0 as confidence, 'job number on the monitoring feed' as method, false as split_flag
    from intervals i
    where i.assigned_job_id is not null

),

unassigned as (

    select i.*
    from intervals i
    where i.assigned_job_id is null

),

-- every part the program could mean, with the routing operation on this cell
part_candidates as (

    select u.interval_id, c.part_number, c.confidence as crosswalk_confidence, c.unique_program
    from unassigned u
    join crosswalk c using (program_number)
    join {{ ref('stg_erp__routings') }} r
      on r.part_number = c.part_number and r.program_number = u.program_number
     and left(r.work_center_id, 3) = u.work_center_group
    where not exists (select 1 from unresolved_pairs x where x.program_number = u.program_number and x.machine_id = u.machine_id)

),

-- the jobs open for those parts on the interval's date
job_candidates as (

    select
        pc.interval_id, pc.unique_program, pc.crosswalk_confidence,
        j.job_id, j.quantity,
        count(*) over (partition by pc.interval_id) as open_jobs,
        sum(j.quantity) over (partition by pc.interval_id) as open_quantity
    from part_candidates pc
    join unassigned u using (interval_id)
    join {{ ref('stg_erp__jobs') }} j
      on j.part_number = pc.part_number
     and j.release_date <= u.interval_date
     and coalesce(j.completed_date, cast('{{ var("end_date") }}' as date)) >= u.interval_date

),

-- a program unique to one part with no job open on the day: the nearest release within thirty days
nearest as (

    select interval_id, job_id
    from (
        select pc.interval_id, j.job_id,
               row_number() over (partition by pc.interval_id order by abs(date_diff('day', j.release_date, u.interval_date)), j.job_id) as rn
        from part_candidates pc
        join unassigned u using (interval_id)
        join {{ ref('stg_erp__jobs') }} j
          on j.part_number = pc.part_number
         and abs(date_diff('day', j.release_date, u.interval_date)) <= 30
        where pc.unique_program
          and pc.interval_id not in (select interval_id from job_candidates)
    )
    where rn = 1

),

matched as (

    select u.*, c.job_id, c.quantity / c.open_quantity as share,
           c.crosswalk_confidence * case when c.open_jobs = 1 then 0.95 else 0.6 end as confidence,
           case when c.open_jobs = 1 and c.unique_program then 'crosswalk, one open job for the part'
                when c.open_jobs = 1 then 'shared program, one open job among the parts using it'
                else 'crosswalk, split across ' || c.open_jobs || ' open jobs by quantity' end as method,
           c.open_jobs > 1 as split_flag
    from unassigned u
    join job_candidates c using (interval_id)

    union all

    select u.*, n.job_id, 1.0 as share, 0.5 as confidence,
           'crosswalk, nearest release within thirty days' as method, false as split_flag
    from unassigned u
    join nearest n using (interval_id)

    union all

    select u.*, null as job_id, 1.0 as share, 0.0 as confidence,
           case when exists (select 1 from unresolved_pairs x where x.program_number = u.program_number and x.machine_id = u.machine_id)
                     then 'unresolved program on this machine'
                when u.interval_id not in (select interval_id from part_candidates) then 'program not in the crosswalk'
                else 'no job open for the program''s parts on the day' end as method,
           false as split_flag
    from unassigned u
    where u.interval_id not in (select interval_id from job_candidates)
      and u.interval_id not in (select interval_id from nearest)

)

select interval_id, machine_id, start_time, end_time, state, program_number, cycle_count, hours, interval_date,
       job_id, share, hours * share as assigned_hours, confidence, method, split_flag
from erp_assigned
union all
select interval_id, machine_id, start_time, end_time, state, program_number, cycle_count, hours, interval_date,
       job_id, share, hours * share as assigned_hours, confidence, method, split_flag
from matched
