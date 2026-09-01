-- Indirect time charged to jobs. Short records that started within an hour of
-- the start of an earlier record of the same operator on the same job that was
-- still open: waiting, meetings and cleanup posted against whatever job was up.
-- On monitored cells the machine sat idle through the record.

select
    l.txn_id,
    l.job_id,
    l.op_seq,
    l.work_center_id,
    l.employee_id,
    l.clock_on,
    l.clock_off,
    l.hours,
    o.start_gap_hours,
    o.earlier_record_hours,
    o.machine_active_ratio,
    case when o.machine_active_ratio < 0.3 then 'posted on top of an open record; machine idle'
         else 'posted on top of an open record on the same job' end as evidence,
    case when o.machine_active_ratio < 0.3 then 0.85
         else 0.65 end                               as confidence
from {{ ref('stg_erp__labor_transactions') }} l
join {{ ref('int_labor_machine_overlap') }} o using (txn_id)
where l.labor_type = 'run'
  and l.source = 'terminal'
  and l.job_id is not null
  and l.op_seq <> 999
  and not l.after_codes
  and l.hours between 0.4 and 2.3
  and o.start_gap_hours between 0 and 0.9
  and o.earlier_record_hours < {{ var('open_record_hours') }}
