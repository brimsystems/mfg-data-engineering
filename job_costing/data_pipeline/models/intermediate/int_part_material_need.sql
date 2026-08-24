-- Material per piece by part, measured from the issues on the part's jobs. A job
-- that received another job's bar, or whose remnant was never issued, sits far from
-- the rest, so the need is taken from the largest cluster of jobs that agree with
-- each other (within 15%); where no two jobs agree, the lowest job is used, since
-- bar charged to the wrong job inflates a job far more than a missing remnant
-- deflates one.

with by_job as (

    select m.job_id, j.part_number, j.quantity, m.uom, sum(m.quantity) / j.quantity as per_piece
    from {{ ref('stg_erp__material_transactions') }} m
    join {{ ref('stg_erp__jobs') }} j using (job_id)
    where j.quantity > 0
    group by m.job_id, j.part_number, j.quantity, m.uom
    having sum(m.quantity) > 0

),

-- for every job, how many of the part's jobs sit within 15% of it
neighbors as (

    select a.part_number, a.uom, a.job_id, a.per_piece,
           count(*) as agreeing
    from by_job a
    join by_job b
      on b.part_number = a.part_number and b.uom = a.uom
     and abs(b.per_piece / a.per_piece - 1) <= 0.15
    group by 1, 2, 3, 4

),

-- the centre of the largest cluster (ties to the lowest)
anchor as (

    select part_number, uom, per_piece as anchor_per_piece
    from (
        select *, row_number() over (partition by part_number, uom order by agreeing desc, per_piece) as rn
        from neighbors
    )
    where rn = 1

),

counts as (

    select part_number, uom, count(*) as jobs_measured from by_job group by 1, 2

)

select
    b.part_number,
    b.uom,
    median(b.per_piece)                      as need_per_piece,
    max(c.jobs_measured)                     as jobs_measured,
    count(*)                                 as jobs_in_cluster
from by_job b
join anchor a using (part_number, uom)
join counts c using (part_number, uom)
where abs(b.per_piece / a.anchor_per_piece - 1) <= 0.15
group by 1, 2
