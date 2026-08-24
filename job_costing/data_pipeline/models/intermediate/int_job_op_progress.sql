-- Each job's routing, one row per cell group in routing order, with the estimate
-- spread over the operations, the corrected hours actually worked there and the
-- last activity at the cell. This is what the job in progress screen reads: the
-- estimate to date against the actual to date as the job moves down its routing.
-- The estimate per operation is the routing standard (setup plus quantity times
-- the run standard) scaled so the operations sum to the job's estimated hours.
-- Grain: job, cell group.

with jobs as (

    select job_id, part_number, quantity from {{ ref('stg_erp__jobs') }}

),

route as (

    select part_number, left(work_center_id, 3) as work_center_group, min(op_seq) as op_seq,
           sum(std_setup_hours) as std_setup_hours, sum(std_run_min_per_piece) as std_run_min_per_piece
    from {{ ref('stg_erp__routings') }}
    group by 1, 2

),

op_standard as (

    select j.job_id, r.work_center_group, r.op_seq, r.std_setup_hours,
           r.std_setup_hours + j.quantity * r.std_run_min_per_piece / 60.0 as std_hours
    from jobs j
    join route r using (part_number)

),

op_estimate as (

    select o.job_id, o.work_center_group, o.op_seq, o.std_setup_hours,
           o.std_hours / nullif(sum(o.std_hours) over (partition by o.job_id), 0)
             * (e.est_setup_hours + e.est_run_hours) as est_hours
    from op_standard o
    join {{ ref('int_estimate_by_job') }} e using (job_id)

),

op_actual as (

    select job_id, left(work_center_id, 3) as work_center_group,
           sum(setup_hours + run_hours + rework_hours) as act_hours,
           sum(setup_hours)                            as act_setup_hours
    from {{ ref('int_labor_hours_by_job') }}
    group by 1, 2

),

activity as (

    select job_id, left(work_center_id, 3) as work_center_group, max(last_activity) as last_activity
    from {{ ref('int_machine_hours_by_job') }}
    group by 1, 2
    union all
    select corrected_job_id as job_id, left(work_center_id, 3) as work_center_group, max(clock_off) as last_activity
    from {{ ref('int_labor_cleaned') }}
    where corrected_job_id is not null and status in ('corrected', 'as recorded', 'scan')
    group by 1, 2

),

op_end as (

    select job_id, work_center_group, max(last_activity) as op_end
    from activity
    group by 1, 2

)

select
    e.job_id,
    e.work_center_group,
    e.op_seq,
    row_number() over (partition by e.job_id order by e.op_seq)                                   as op_index,
    count(*) over (partition by e.job_id)                                                         as ops,
    e.est_hours,
    coalesce(a.act_hours, 0)                                                                      as act_hours,
    e.std_setup_hours,
    a.act_setup_hours,
    sum(e.est_hours) over (partition by e.job_id order by e.op_seq rows unbounded preceding)       as cum_est_hours,
    sum(coalesce(a.act_hours, 0)) over (partition by e.job_id order by e.op_seq rows unbounded preceding) as cum_act_hours,
    x.op_end
from op_estimate e
left join op_actual a using (job_id, work_center_group)
left join op_end x using (job_id, work_center_group)
