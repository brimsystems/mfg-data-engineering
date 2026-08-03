-- T1: jobs left clocked in. Records that ran across a break, a shift end or the
-- night. A record beyond the open-record threshold is flagged outright. Shorter
-- ones are flagged when they ran past the start of the operator's next record on
-- the same job; on monitored cells that signature is shared with multi-machine
-- tending (T4), so the split between the two there is by the size of the overrun,
-- and both corrections come to the same thing: the machine's own hours.

with labor as (

    select l.*, w.monitored_flag, w.work_center_group,
           o.machine_active_hours, o.machine_active_ratio, o.overrun_hours, o.next_start_gap_hours,
           cast(clock_on as date) <> cast(clock_off as date)                     as spans_midnight,
           floor((extract(epoch from clock_on) / 3600 - 6) / 8) <> floor((extract(epoch from clock_off) / 3600 - 6) / 8) as spans_shift_end
    from {{ ref('stg_erp__labor_transactions') }} l
    join {{ ref('stg_erp__work_centers') }} w using (work_center_id)
    join {{ ref('int_labor_machine_overlap') }} o using (txn_id)
    where l.labor_type <> 'indirect' and l.job_id is not null and l.source = 'terminal' and l.op_seq <> 999
      and not l.after_codes

)

select
    txn_id,
    job_id,
    op_seq,
    work_center_id,
    work_center_group,
    employee_id,
    clock_on,
    clock_off,
    hours,
    spans_midnight,
    spans_shift_end,
    monitored_flag,
    machine_active_hours,
    machine_active_ratio,
    overrun_hours,
    case when hours >= {{ var('open_record_hours') }} and monitored_flag then greatest(0, hours - machine_active_hours)
         when hours >= {{ var('open_record_hours') }} then greatest(0, hours - 2.5)
         else overrun_hours end                     as inflated_hours,
    case when hours >= 8 and spans_midnight then 'overnight'
         when hours >= {{ var('open_record_hours') }} or spans_shift_end then 'shift end'
         else 'break' end                            as span_kind,
    case when hours >= {{ var('open_record_hours') }} then 'record beyond the open-record threshold'
         else 'ran past the operator''s next record on the job' end as evidence,
    case when hours >= 8 then 0.95
         when hours >= {{ var('open_record_hours') }} then 0.85
         when not monitored_flag then 0.7
         else 0.6 end                               as confidence
from labor
where hours >= {{ var('open_record_hours') }}
   or (overrun_hours >= 0.4 and next_start_gap_hours >= 0.9 and (not monitored_flag or overrun_hours >= 0.8))
