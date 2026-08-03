-- T4: multi-machine tending recorded as one job. Records on monitored cells that
-- ran past the start of the operator's next record on the same job by less than
-- an hour (a longer overrun is a record left open, T1): the operator had moved to a second or third
-- machine and the door terminal kept the first job open. The excess over the
-- machine's own hours is the time that belongs to the other machines.

select
    l.txn_id,
    l.job_id,
    l.op_seq,
    l.work_center_id,
    w.work_center_group,
    l.employee_id,
    l.clock_on,
    l.clock_off,
    l.hours,
    o.machine_active_hours,
    o.machine_active_ratio,
    o.overrun_hours,
    o.next_start_gap_hours,
    'ran past the operator''s next record on the job; machine hours below the record' as evidence,
    case when o.overrun_hours < 0.5 then 0.7 else 0.6 end as confidence
from {{ ref('stg_erp__labor_transactions') }} l
join {{ ref('stg_erp__work_centers') }} w using (work_center_id)
join {{ ref('int_labor_machine_overlap') }} o using (txn_id)
where w.monitored_flag
  and l.labor_type <> 'indirect'
  and l.source = 'terminal'
  and l.op_seq <> 999
  and not l.after_codes
  and l.hours < {{ var('open_record_hours') }}
  and o.overrun_hours >= 0.4 and o.overrun_hours < 0.8
  and o.next_start_gap_hours >= 0.9
