-- The labor correction log: every clock record with the rule that fired, what
-- changed and the evidence. Records on monitored cells whose job has machine
-- hours are superseded by them; a record left open with no machine data behind
-- it, or charged to a job whose routing does not fit with no adjacent job that
-- does, stays as recorded and is flagged unrepairable.

with labor as (

    select l.*, w.monitored_flag, w.is_secondary
    from {{ ref('stg_erp__labor_transactions') }} l
    join {{ ref('stg_erp__work_centers') }} w using (work_center_id)

),

open_rec as (select txn_id, confidence, machine_active_hours, inflated_hours from {{ ref('dq_open_clock_records') }}),
wrong_job as (select txn_id, confidence, candidate_job_id from {{ ref('dq_wrong_job') }}),
multi as (select txn_id, confidence, machine_active_hours from {{ ref('dq_multi_machine_tending') }}),
indirect as (select txn_id, confidence from {{ ref('dq_indirect_time_on_jobs') }}),

machine_jobs as (

    select distinct job_id, work_center_id from {{ ref('int_machine_hours_by_job') }}

),

ruled as (

    select
        l.*,
        case when l.labor_type = 'indirect' then null
             when indirect.txn_id is not null then null
             else coalesce(wrong_job.candidate_job_id, l.job_id) end                    as corrected_job_id,
        case when l.op_seq = 999 then 'rework' else l.labor_type end             as corrected_type,
        case
            when l.labor_type = 'indirect'                          then 'indirect code, no job'
            when l.source = 'traveler_scan'                         then 'traveler scan'
            when indirect.txn_id is not null                              then 'moved to indirect'
            when wrong_job.candidate_job_id is not null                    then 're-pointed to the adjacent job'
            when wrong_job.txn_id is not null                              then 'routing does not fit, no adjacent job fits'
            when l.op_seq = 999                                     then 'catch-all operation retyped as rework'
            else null end                                                        as first_rule,
        coalesce(indirect.confidence, wrong_job.confidence, open_rec.confidence, multi.confidence)     as confidence
    from labor l
    left join open_rec using (txn_id)
    left join wrong_job using (txn_id)
    left join multi using (txn_id)
    left join indirect using (txn_id)

)

select
    r.txn_id,
    r.job_id,
    r.op_seq,
    r.work_center_id,
    r.employee_id,
    r.clock_on,
    r.clock_off,
    r.hours,
    r.labor_type,
    r.source,
    r.monitored_flag,
    r.after_codes,
    r.corrected_job_id,
    r.corrected_type,
    coalesce(
        r.first_rule,
        case when r.monitored_flag and mj.job_id is not null                    then 'superseded by machine hours'
             when open_rec.txn_id is not null and r.monitored_flag                    then 'left open: capped to machine hours in the window'
             when open_rec.txn_id is not null                                         then 'left open, no machine data'
             when multi.txn_id is not null                                         then 'multi-machine record: machine hours not assignable'
             else 'as recorded' end)                                             as rule,
    case when r.first_rule in ('indirect code, no job', 'moved to indirect')            then 'removed'
         when r.first_rule = 'traveler scan'                                                then 'scan'
         when r.first_rule = 'routing does not fit, no adjacent job fits'               then 'unrepairable'
         when r.first_rule is not null                                                      then 'corrected'
         when r.monitored_flag and mj.job_id is not null                                    then 'superseded'
         when open_rec.txn_id is not null and r.monitored_flag                                    then 'corrected'
         when open_rec.txn_id is not null or multi.txn_id is not null                                then 'unrepairable'
         else 'as recorded' end                                                  as status,
    case when r.first_rule = 'routing does not fit, no adjacent job fits' then r.hours
         when r.first_rule is not null or (r.monitored_flag and mj.job_id is not null) then r.hours
         when open_rec.txn_id is not null and r.monitored_flag then greatest(open_rec.machine_active_hours, 0.25)
         else r.hours end                                                        as corrected_hours,
    r.confidence
from ruled r
left join open_rec using (txn_id)
left join multi using (txn_id)
left join machine_jobs mj on mj.job_id = r.corrected_job_id and mj.work_center_id = r.work_center_id
