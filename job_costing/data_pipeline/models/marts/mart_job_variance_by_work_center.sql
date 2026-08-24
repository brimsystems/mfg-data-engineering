-- Setup and run hours against estimate by work center, for the Work center grouping of
-- the Job Variance report. The estimate for an operation is the routing standard for its
-- cell (setup, and run at the job's quantity), scaled so the job's operations sum to its
-- estimated setup and run hours. A job's operation is kept where it ran on one work
-- center, so the ratio belongs to that machine. Grain: completed job, work center.

with jobs as (

    select job_id, part_number, quantity, completed_date from {{ ref('stg_erp__jobs') }} where status = 'completed'

),

route as (

    select part_number, left(work_center_id, 3) as work_center_group,
           sum(std_setup_hours) as std_setup_hours, sum(std_run_min_per_piece) as std_run_min_per_piece
    from {{ ref('stg_erp__routings') }}
    group by 1, 2

),

op_std as (

    select j.job_id, r.work_center_group, r.std_setup_hours, j.quantity * r.std_run_min_per_piece / 60.0 as std_run_hours
    from jobs j join route r using (part_number)

),

op_est as (

    select o.job_id, o.work_center_group,
           o.std_setup_hours / nullif(sum(o.std_setup_hours) over (partition by o.job_id), 0) * e.est_setup_hours as est_setup_hours,
           o.std_run_hours / nullif(sum(o.std_run_hours) over (partition by o.job_id), 0) * e.est_run_hours       as est_run_hours
    from op_std o
    join {{ ref('int_estimate_by_job') }} e using (job_id)

),

actual as (

    select job_id, work_center_id, left(work_center_id, 3) as work_center_group,
           sum(setup_hours) as act_setup_hours, sum(run_hours) as act_run_hours
    from {{ ref('int_labor_hours_by_job') }}
    group by 1, 2, 3

),

single as (

    select a.*, count(*) over (partition by a.job_id, a.work_center_group) as machines_in_cell
    from actual a

)

select
    s.job_id, j.completed_date, s.work_center_id, s.work_center_group, w.work_center_type, w.monitored_flag,
    o.est_setup_hours, s.act_setup_hours, o.est_run_hours, s.act_run_hours,
    s.act_setup_hours / nullif(o.est_setup_hours, 0) as ratio_setup,
    s.act_run_hours / nullif(o.est_run_hours, 0)     as ratio_run
from single s
join jobs j using (job_id)
join op_est o using (job_id, work_center_group)
join {{ ref('stg_erp__work_centers') }} w on w.work_center_id = s.work_center_id
where s.machines_in_cell = 1
