-- Time charged to the wrong job. Records whose job has no routing operation
-- at that sequence in that cell. The evidence is the adjacent job number whose
-- routing does fit and which was open on the day.

with labor as (

    select l.txn_id, l.job_id, l.op_seq, l.work_center_id, l.employee_id, l.clock_on, l.clock_off, l.hours, l.clock_date,
           j.part_number, j.release_date, j.completed_date,
           cast(substr(l.job_id, 3) as integer) as job_seq
    from {{ ref('stg_erp__labor_transactions') }} l
    join {{ ref('stg_erp__jobs') }} j using (job_id)
    where l.labor_type <> 'indirect' and l.op_seq <> 999

),

routing_fit as (

    select l.txn_id,
           bool_or(r.op_seq = l.op_seq and left(r.work_center_id, 3) = left(l.work_center_id, 3)) as op_on_routing,
           bool_or(left(r.work_center_id, 3) = left(l.work_center_id, 3))                           as work_center_on_routing
    from labor l
    join {{ ref('stg_erp__routings') }} r on r.part_number = l.part_number
    group by 1

),

suspect as (

    select l.*, f.op_on_routing, f.work_center_on_routing,
           l.clock_date < l.release_date or l.clock_date > coalesce(l.completed_date, cast('{{ var("end_date") }}' as date)) + 1 as outside_job_window
    from labor l
    join routing_fit f using (txn_id)
    where not f.op_on_routing

),

-- the nearest job number, within three, whose routing has this operation and which was open;
-- of two equally near, the lower number
candidates as (

    select s.txn_id, j.job_id as candidate_job_id,
           row_number() over (partition by s.txn_id order by abs(cast(substr(j.job_id, 3) as integer) - s.job_seq), j.job_id) as rn
    from suspect s
    join {{ ref('stg_erp__jobs') }} j
      on abs(cast(substr(j.job_id, 3) as integer) - s.job_seq) between 1 and 3
     and j.release_date <= s.clock_date
     and coalesce(j.completed_date, cast('{{ var("end_date") }}' as date)) + 1 >= s.clock_date
    join {{ ref('stg_erp__routings') }} r
      on r.part_number = j.part_number and r.op_seq = s.op_seq and left(r.work_center_id, 3) = left(s.work_center_id, 3)

)

select
    s.txn_id,
    s.job_id,
    s.op_seq,
    s.work_center_id,
    s.employee_id,
    s.clock_on,
    s.hours,
    s.part_number,
    s.release_date,
    s.completed_date,
    s.op_on_routing,
    s.work_center_on_routing,
    s.outside_job_window,
    c.candidate_job_id,
    case when s.outside_job_window then 'operation not on the routing and job not open'
         else 'operation not on the job''s routing' end as evidence,
    case when c.candidate_job_id is not null then 0.95
         when s.outside_job_window then 0.8
         else 0.6 end                                as confidence
from suspect s
left join candidates c on c.txn_id = s.txn_id and c.rn = 1
