-- For every clock record: how much of its window the machine spent on an
-- operation (monitored cells), and how the record sits against the operator's other
-- records on the same job. A record that runs past the start of the operator's next
-- record on the same job was left open; a short record that starts inside an
-- earlier record on the same job was posted on top of it. The evidence behind the open records,
-- the multi-machine records and the indirect time on jobs.

with labor as (

    select l.txn_id, l.job_id, l.op_seq, l.work_center_id, l.employee_id, l.clock_on, l.clock_off, l.hours, l.labor_type,
           w.monitored_flag, w.machine_id
    from {{ ref('stg_erp__labor_transactions') }} l
    join {{ ref('stg_erp__work_centers') }} w using (work_center_id)
    where l.job_id is not null and l.labor_type <> 'indirect'

),

machine as (

    select l.txn_id,
           sum(greatest(0, date_diff('second', greatest(l.clock_on, m.start_time), least(l.clock_off, m.end_time)) / 3600.0)) as machine_active_hours
    from labor l
    join {{ ref('stg_monitoring__machine_monitoring') }} m
      on m.machine_id = l.machine_id
     and (m.state in ('setup', 'in_cycle', 'alarm') or (m.state = 'idle' and m.program_number is not null))
     and m.start_time < l.clock_off
     and m.end_time > l.clock_on
    where l.monitored_flag
    group by 1

),

-- this record ran past the start of the operator's next record on the same job
runs_over as (

    select a.txn_id,
           max(date_diff('second', b.clock_on, a.clock_off) / 3600.0)   as overrun_hours,
           min(date_diff('second', a.clock_on, b.clock_on) / 3600.0)    as next_start_gap_hours
    from labor a
    join labor b
      on b.employee_id = a.employee_id
     and b.job_id = a.job_id
     and b.txn_id <> a.txn_id
     and b.clock_on > a.clock_on
     and b.clock_on < a.clock_off - interval 5 minute
    group by 1

),

-- this record started inside an earlier record of the operator on the same job
starts_inside as (

    select a.txn_id,
           min(date_diff('second', b.clock_on, a.clock_on) / 3600.0)    as start_gap_hours,
           max(b.hours)                                                 as earlier_record_hours,
           count(*)                                                     as earlier_records
    from labor a
    join labor b
      on b.employee_id = a.employee_id
     and b.job_id = a.job_id
     and b.txn_id <> a.txn_id
     and b.clock_on < a.clock_on
     and b.clock_off > a.clock_on + interval 5 minute
    group by 1

)

select
    l.txn_id,
    l.monitored_flag,
    coalesce(m.machine_active_hours, 0)                                          as machine_active_hours,
    case when l.monitored_flag then coalesce(m.machine_active_hours, 0) / nullif(l.hours, 0) end as machine_active_ratio,
    coalesce(r.overrun_hours, 0)                                                 as overrun_hours,
    r.next_start_gap_hours,
    s.start_gap_hours,
    s.earlier_record_hours,
    coalesce(s.earlier_records, 0)                                               as earlier_records
from labor l
left join machine m using (txn_id)
left join runs_over r using (txn_id)
left join starts_inside s using (txn_id)
