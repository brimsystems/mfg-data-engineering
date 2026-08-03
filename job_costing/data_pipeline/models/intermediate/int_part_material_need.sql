-- Material per piece by part, measured from the issues on the part's jobs (the
-- median across jobs, so a job that received another job's bar does not move it).

with by_job as (

    select m.job_id, j.part_number, j.quantity, m.uom, sum(m.quantity) as issued
    from {{ ref('stg_erp__material_transactions') }} m
    join {{ ref('stg_erp__jobs') }} j using (job_id)
    group by 1, 2, 3, 4

)

select
    part_number,
    uom,
    median(issued / quantity)                as need_per_piece,
    count(*)                                 as jobs_measured
from by_job
where quantity > 0
group by 1, 2
