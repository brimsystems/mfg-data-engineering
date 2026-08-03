-- The estimate each job is measured against: the estimate carried on the job
-- after the configuration change, the engagement's backfill from the quoting
-- module before it, and the routing standard at the shop rate where no quote
-- line could be found.

with backfill as (

    select * from {{ ref('stg_remediation__estimate_backfill') }} where est_total_cost is not null

),

standard as (

    select j.job_id,
           sum(r.std_setup_hours)                                    as est_setup_hours,
           sum(r.std_run_min_per_piece / 60.0 * j.quantity)          as est_run_hours,
           max(rt.blended_rate)                                      as rate
    from {{ ref('stg_erp__jobs') }} j
    join {{ ref('stg_erp__routings') }} r using (part_number)
    join {{ ref('int_rates') }} rt on rt.work_center_id = (select min(work_center_id) from {{ ref('int_rates') }})
                                   and rt.year = extract(year from j.release_date)
    group by 1

),

material_std as (

    select j.job_id, j.quantity * n.need_per_piece * m.unit_cost as est_material
    from {{ ref('stg_erp__jobs') }} j
    join {{ ref('int_part_material_need') }} n using (part_number)
    join {{ ref('stg_erp__part_master') }} p using (part_number)
    join {{ ref('int_material_price_monthly') }} m
      on m.material_spec = p.material_spec and m.uom = n.uom and m.month = date_trunc('month', j.release_date)

),

estimator as (

    select q.quote_id, min(q.estimator_id) as estimator_id, min(q.estimate_basis) as estimate_basis
    from {{ ref('stg_erp__quotes') }} q group by 1

)

select
    j.job_id,
    case when j.est_total_cost is not null then 'job'
         when b.job_id is not null then 'backfill'
         else 'standard-fallback' end                                                as estimate_source,
    case when j.est_total_cost is not null then 'carried from the quote on conversion'
         when b.job_id is not null then b.method
         else 'routing standard at the shop rate, material at the month''s price' end as estimate_method,
    case when j.est_total_cost is not null then 1.0
         when b.job_id is not null then b.match_confidence else 0.3 end             as estimate_confidence,
    coalesce(j.est_material, b.est_material, ms.est_material, 0)                     as est_material,
    coalesce(j.est_setup_hours, b.est_setup_hours, s.est_setup_hours)                as est_setup_hours,
    coalesce(j.est_run_hours, b.est_run_hours, s.est_run_hours)                      as est_run_hours,
    coalesce(j.est_outside, b.est_outside, 0)                                        as est_outside,
    coalesce(j.est_total_cost, b.est_total_cost,
             coalesce(ms.est_material, 0) + (s.est_setup_hours + s.est_run_hours) * s.rate) as est_total_cost,
    coalesce(j.est_total_cost, b.est_total_cost,
             coalesce(ms.est_material, 0) + (s.est_setup_hours + s.est_run_hours) * s.rate)
      - coalesce(j.est_material, b.est_material, ms.est_material, 0)
      - coalesce(j.est_outside, b.est_outside, 0)                                    as est_labor,
    coalesce(j.quote_id, b.quote_id)                                                 as quote_id,
    e.estimator_id,
    e.estimate_basis
from {{ ref('stg_erp__jobs') }} j
left join backfill b using (job_id)
left join standard s using (job_id)
left join material_std ms using (job_id)
left join estimator e on e.quote_id = coalesce(j.quote_id, b.quote_id)
