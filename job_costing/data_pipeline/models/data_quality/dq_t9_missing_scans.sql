-- T9: missing scans during the rollout. Secondary operations the job has reached
-- since the traveler-scanning pilot began with no scan record: every secondary operation on
-- jobs released after the start, and on jobs already in process the operations
-- that followed the last one clocked before the start.

with last_before as (

    select job_id, max(op_seq) as last_op_before_rollout
    from {{ ref('stg_erp__labor_transactions') }}
    where source = 'terminal' and clock_date < cast('{{ var("scan_rollout_date") }}' as date)
    group by 1

),

-- how far each job has got: the highest operation with any record against it
reached as (

    select job_id, max(op_seq) as reached_op_seq
    from {{ ref('stg_erp__labor_transactions') }}
    where job_id is not null and op_seq <> 999
    group by 1

),

expected as (

    select j.job_id, j.release_date, r.op_seq, r.work_center_id,
           least(12, greatest(1, (date_diff('day', cast('{{ var("engagement_start") }}' as date),
                 greatest(j.release_date, cast('{{ var("scan_rollout_date") }}' as date))) // 7) + 1)) as engagement_week
    from {{ ref('stg_erp__jobs') }} j
    join {{ ref('stg_erp__routings') }} r using (part_number)
    join {{ ref('stg_erp__work_centers') }} w using (work_center_id)
    left join last_before b using (job_id)
    left join reached rc using (job_id)
    where w.is_secondary
      and (j.release_date >= cast('{{ var("scan_rollout_date") }}' as date)
           or (coalesce(j.completed_date, cast('{{ var("end_date") }}' as date)) >= cast('{{ var("scan_rollout_date") }}' as date) + 2
               and r.op_seq > coalesce(b.last_op_before_rollout, 0)))
      -- an operation is expected only once the job has reached it: the job is complete, or a later operation has a record
      and (j.status = 'completed' or r.op_seq < coalesce(rc.reached_op_seq, 0))

),

scanned as (

    select distinct job_id, op_seq
    from {{ ref('stg_erp__labor_transactions') }}
    where source = 'traveler_scan'

)

select
    e.job_id,
    e.op_seq,
    e.work_center_id,
    e.release_date,
    e.engagement_week,
    'no traveler scan on a secondary operation'     as evidence,
    0.9                                             as confidence
from expected e
left join scanned s using (job_id, op_seq)
where s.job_id is null
