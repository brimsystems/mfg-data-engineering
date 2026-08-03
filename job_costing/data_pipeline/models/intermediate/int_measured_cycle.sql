-- Cycle and setup time as the machines measured them, per program, mapped to the
-- routing operation through the program crosswalk. Only programs that resolve to a
-- single part carry a measurement.

with by_program as (

    select
        program_number,
        sum(case when state = 'in_cycle' then hours end)                       as in_cycle_hours,
        sum(case when state = 'in_cycle' then cycle_count end)                 as cycles,
        median(case when state = 'setup' and hours < 12 then hours end)        as measured_setup_hours,
        count(distinct case when state = 'setup' then interval_date end)       as setup_episodes,
        count(distinct machine_id)                                             as machines_used
    from {{ ref('stg_monitoring__machine_monitoring') }}
    where program_number is not null
    group by 1

),

crosswalk as (

    select program_number, part_number, confidence as crosswalk_confidence, method
    from {{ ref('stg_remediation__program_crosswalk') }}
    where status = 'resolved' and method = 'routing match'

)

select
    c.part_number,
    r.op_seq,
    r.work_center_id,
    p.program_number,
    r.std_run_min_per_piece,
    r.std_setup_hours,
    p.in_cycle_hours * 60.0 / nullif(p.cycles, 0) as measured_run_min_per_piece,
    p.measured_setup_hours,
    p.cycles,
    p.setup_episodes,
    p.machines_used,
    c.crosswalk_confidence,
    c.method                                     as crosswalk_method
from by_program p
join crosswalk c using (program_number)
join {{ ref('stg_erp__routings') }} r
  on r.part_number = c.part_number and r.program_number = p.program_number
where p.cycles >= 20
