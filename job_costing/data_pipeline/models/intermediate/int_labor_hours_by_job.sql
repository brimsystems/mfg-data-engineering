-- Corrected labor hours per job and work center with the source of each figure:
-- machine hours where the cell is monitored and the job's hours could be assigned,
-- the corrected clock records elsewhere, traveler scans at the secondary
-- operations, the routing standard where nothing was recorded, and the records
-- that could not be repaired. Grain: job, work center, source.

with machine as (

    select job_id, work_center_id, 'machine' as source,
           machine_setup_hours as setup_hours, machine_run_hours + machine_alarm_hours + machine_idle_hours as run_hours, 0.0 as rework_hours,
           machine_hours as hours, assignment_confidence as confidence
    from {{ ref('int_machine_hours_by_job') }}

),

clock as (

    select corrected_job_id as job_id, work_center_id,
           case when status = 'unrepairable' then 'unrepairable'
                when status = 'scan' then 'scan' else 'clock' end as source,
           sum(case when corrected_type = 'setup' then corrected_hours else 0 end)  as setup_hours,
           sum(case when corrected_type = 'run' then corrected_hours else 0 end)    as run_hours,
           0.0 as rework_hours,
           sum(corrected_hours) as hours,
           avg(coalesce(confidence, 1.0)) as confidence
    from {{ ref('int_labor_cleaned') }}
    where status in ('corrected', 'unrepairable', 'as recorded', 'scan')
      and corrected_job_id is not null
      and corrected_type <> 'rework'
    group by 1, 2, 3

),

-- rework is not machine time: the record stands whether or not the cell is monitored
rework as (

    select corrected_job_id as job_id, work_center_id, 'clock' as source,
           0.0 as setup_hours, 0.0 as run_hours, sum(corrected_hours) as rework_hours, sum(corrected_hours) as hours,
           avg(coalesce(confidence, 1.0)) as confidence
    from {{ ref('int_labor_cleaned') }}
    where status in ('corrected', 'as recorded', 'superseded')
      and corrected_job_id is not null
      and corrected_type = 'rework'
    group by 1, 2, 3

),

clock_kept as (

    -- clock records only where the machine did not measure the job on that cell
    select c.*
    from clock c
    left join machine m using (job_id, work_center_id)
    where m.job_id is null

),

recorded_cells as (

    select job_id, left(work_center_id, 3) as work_center_group from machine
    union
    select job_id, left(work_center_id, 3) from clock_kept

),

-- routing operations with nothing recorded in their cell fall back to the standard
fallback as (

    select j.job_id, r.work_center_id, 'standard-fallback' as source,
           sum(r.std_setup_hours) as setup_hours,
           sum(r.std_run_min_per_piece / 60.0 * j.quantity) as run_hours,
           0.0 as rework_hours,
           sum(r.std_setup_hours + r.std_run_min_per_piece / 60.0 * j.quantity) as hours,
           0.0 as confidence
    from {{ ref('stg_erp__jobs') }} j
    join {{ ref('stg_erp__routings') }} r using (part_number)
    left join recorded_cells rc on rc.job_id = j.job_id and rc.work_center_group = left(r.work_center_id, 3)
    where rc.job_id is null
    group by 1, 2, 3

)

select * from machine
union all
select * from clock_kept
union all
select * from rework
union all
select * from fallback
