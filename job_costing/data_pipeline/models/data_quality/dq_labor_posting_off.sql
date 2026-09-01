-- Labor posting never turned on at three secondary cells. The routing names a
-- nominal cell and the scheduler ran the operation on any cell in its group, so the
-- test is at the group level: operations in the deburr, inspection and drill groups
-- on jobs released before the scanning rollout with no labor record of any kind. The
-- other cells in those groups posted every operation they ran; the missing ones ran
-- on the cells that never posted. Grain: one row per job and operation.

with no_posting as (

    select distinct left(work_center_id, 3) as work_center_group
    from (select unnest([{{ "'" ~ var('no_posting_work_centers') | join("', '") ~ "'" }}]) as work_center_id)

),

expected as (

    select j.job_id, j.release_date, j.completed_date, r.op_seq, r.work_center_id, r.std_setup_hours, r.std_run_min_per_piece, j.quantity
    from {{ ref('stg_erp__jobs') }} j
    join {{ ref('stg_erp__routings') }} r using (part_number)
    join no_posting n on n.work_center_group = left(r.work_center_id, 3)
    where j.release_date < cast('{{ var("scan_rollout_date") }}' as date)

),

recorded as (

    select distinct job_id, op_seq from {{ ref('stg_erp__labor_transactions') }} where job_id is not null

)

select
    e.job_id,
    e.op_seq,
    e.work_center_id                                                   as routing_work_center_id,
    left(e.work_center_id, 3)                                          as work_center_group,
    e.release_date,
    e.std_setup_hours + e.std_run_min_per_piece / 60.0 * e.quantity    as standard_hours_missing,
    'no labor record of any source on the operation; ran on a cell in the group that never posted' as evidence,
    0.95 as confidence
from expected e
left join recorded r using (job_id, op_seq)
where r.job_id is null
