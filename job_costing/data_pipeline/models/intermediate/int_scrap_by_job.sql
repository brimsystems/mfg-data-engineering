-- Scrap and rework per job: scrapped pieces at the job's material cost per piece,
-- and rework hours where they were recorded as such (the catch-all operation
-- before the codes, the rework code after).

with scrap as (

    select job_id, sum(quantity) as scrap_quantity, count(*) as scrap_events,
           sum(case when reason_code is null then 1 else 0 end) as scrap_events_no_reason
    from {{ ref('stg_erp__scrap_rework') }}
    where event_type = 'scrap' and job_id is not null
    group by 1

),

rework_events as (

    select job_id, count(*) as rework_events, sum(quantity) as rework_quantity
    from {{ ref('stg_erp__scrap_rework') }}
    where event_type = 'rework' and job_id is not null
    group by 1

),

per_piece as (

    select job_id, material_corrected / nullif(need_quantity, 0) * need_quantity / nullif(j.quantity, 0) as material_per_piece
    from {{ ref('int_material_by_job') }}
    join {{ ref('stg_erp__jobs') }} j using (job_id)

)

select
    j.job_id,
    coalesce(s.scrap_quantity, 0)                                   as scrap_quantity,
    coalesce(s.scrap_events, 0)                                     as scrap_events,
    coalesce(s.scrap_events_no_reason, 0)                           as scrap_events_no_reason,
    coalesce(s.scrap_quantity, 0) * coalesce(p.material_per_piece, 0) as scrap_material,
    coalesce(r.rework_events, 0)                                    as rework_events,
    coalesce(r.rework_quantity, 0)                                  as rework_quantity
from {{ ref('stg_erp__jobs') }} j
left join scrap s using (job_id)
left join rework_events r using (job_id)
left join per_piece p using (job_id)
