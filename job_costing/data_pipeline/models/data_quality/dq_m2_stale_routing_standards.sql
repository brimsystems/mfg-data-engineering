-- M2: stale routing standards. Repeat-part operations whose standard cycle time,
-- as the ERP held it before the engagement's refresh, differs from what the
-- machines measured by more than the tolerance.

select
    m.part_number,
    m.op_seq,
    m.work_center_id,
    m.program_number,
    p.first_quote_date                              as standard_set_at,
    coalesce(s.old_std_run_min, m.std_run_min_per_piece)  as std_run_min_per_piece,
    m.measured_run_min_per_piece,
    m.measured_run_min_per_piece / coalesce(s.old_std_run_min, m.std_run_min_per_piece) - 1 as run_gap_share,
    coalesce(s.old_std_setup_hours, m.std_setup_hours)    as std_setup_hours,
    m.measured_setup_hours,
    m.measured_setup_hours / nullif(coalesce(s.old_std_setup_hours, m.std_setup_hours), 0) - 1 as setup_gap_share,
    m.cycles                                        as pieces_measured,
    m.crosswalk_confidence,
    case when m.measured_run_min_per_piece < coalesce(s.old_std_run_min, m.std_run_min_per_piece) then 'cycle now faster than standard'
         else 'cycle now slower than standard' end  as direction,
    s.reviewer_decision                             as refresh_decision
from {{ ref('int_measured_cycle') }} m
join {{ ref('stg_erp__part_master') }} p using (part_number)
left join {{ ref('stg_remediation__standard_update_log') }} s using (part_number, op_seq)
where p.part_type = 'repeat'
  and abs(m.measured_run_min_per_piece / coalesce(s.old_std_run_min, m.std_run_min_per_piece) - 1) > {{ var('stale_standard_tolerance') }}
