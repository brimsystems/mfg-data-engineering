-- Generic program numbers. Routing operations whose program is named
-- generically or is shared by more than one part, so the program-to-part mapping
-- the monitoring data depends on breaks.

with usage as (

    select program_number, count(distinct part_number) as parts_using, count(*) as operations_using
    from {{ ref('stg_erp__routings') }}
    where program_number is not null
    group by 1

)

select
    r.part_number,
    r.op_seq,
    r.work_center_id,
    r.program_number,
    u.parts_using,
    u.operations_using,
    case when not regexp_matches(r.program_number, '^O[0-9]{5}$') and u.parts_using > 1 then 'generic name, reused across parts'
         when not regexp_matches(r.program_number, '^O[0-9]{5}$') then 'generic name'
         else 'reused across parts' end            as evidence,
    c.status                                        as crosswalk_status,
    c.method                                        as crosswalk_method
from {{ ref('stg_erp__routings') }} r
join usage u using (program_number)
left join {{ ref('stg_remediation__program_crosswalk') }} c
  on c.program_number = r.program_number and c.machine_id = r.work_center_id and c.part_number = r.part_number
where not regexp_matches(r.program_number, '^O[0-9]{5}$') or u.parts_using > 1
