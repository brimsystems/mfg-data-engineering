-- Does the machine a job runs on change what it takes? For every part that ran on
-- both an older and a newer machine in the same cell, the median run hours per
-- piece the monitoring feed measured on each, and the ratio. Older means installed
-- in or before the year set in the project vars. Grain: part, cell group.

with runs as (

    select h.job_id, j.part_number, h.work_center_id, left(h.work_center_id, 3) as work_center_group,
           w.install_year <= {{ var('older_machine_install_year') }} as older_machine,
           h.machine_run_hours / nullif(j.quantity, 0) as run_hours_per_piece
    from {{ ref('int_machine_hours_by_job') }} h
    join {{ ref('stg_erp__jobs') }} j using (job_id)
    join {{ ref('stg_erp__work_centers') }} w using (work_center_id)
    where h.machine_run_hours > 0

),

by_part as (

    select part_number, work_center_group,
           median(case when older_machine then run_hours_per_piece end)     as older_run_hours_per_piece,
           median(case when not older_machine then run_hours_per_piece end) as newer_run_hours_per_piece,
           count(distinct case when older_machine then job_id end)          as older_jobs,
           count(distinct case when not older_machine then job_id end)      as newer_jobs
    from runs
    group by 1, 2

)

select *, older_run_hours_per_piece / nullif(newer_run_hours_per_piece, 0) as older_over_newer
from by_part
where older_jobs > 0 and newer_jobs > 0
