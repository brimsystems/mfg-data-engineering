-- T7: scrap without reason or without job, and scrap never recorded at all. The
-- recorded gaps are certain; the unrecorded events are inferred from jobs that drew
-- a few percent more stock than the part needs with no scrap event against them.

with need as (

    select j.job_id, j.part_number, j.quantity, n.need_per_piece, sum(m.quantity) / (j.quantity * n.need_per_piece) as issued_ratio
    from {{ ref('stg_erp__jobs') }} j
    join {{ ref('int_part_material_need') }} n using (part_number)
    join {{ ref('stg_erp__material_transactions') }} m using (job_id)
    where n.jobs_measured >= 3 and j.release_date < cast('{{ var("scrap_reason_date") }}' as date)
    group by 1, 2, 3, 4

),

with_event as (

    select distinct job_id from {{ ref('stg_erp__scrap_rework') }} where job_id is not null

)

select
    event_id,
    job_id,
    op_seq,
    event_type,
    quantity,
    reason_code,
    event_date,
    case when job_id is null and reason_code is null then 'no job and no reason code'
         when job_id is null then 'no job number'
         else 'no reason code' end                  as evidence,
    'recorded event'                                as detection,
    0.95                                            as confidence
from {{ ref('stg_erp__scrap_rework') }}
where job_id is null or reason_code is null

union all

select
    null                                            as event_id,
    n.job_id,
    null                                            as op_seq,
    'scrap'                                         as event_type,
    cast(round((n.issued_ratio - 1) * n.quantity) as integer) as quantity,
    null                                            as reason_code,
    null                                            as event_date,
    'stock drawn ' || round((n.issued_ratio - 1) * 100, 1) || '% over the part''s need, no scrap event' as evidence,
    'inferred from material over-issue'             as detection,
    0.5                                             as confidence
from need n
where n.issued_ratio between 1.008 and 1.07
  and n.job_id not in (select job_id from with_event)
  and round((n.issued_ratio - 1) * n.quantity) >= 1
