-- T8: material issued to the wrong job or not issued. Jobs whose issues sit well
-- above or below what the part needs: bar pulled for two jobs and charged to one,
-- or a remnant used and never issued. Grain: one row per affected job.

with by_job as (

    select j.job_id, j.part_number, j.quantity, p.material_spec, j.release_date, n.need_per_piece, n.jobs_measured,
           sum(m.quantity)                              as issued_quantity,
           sum(m.value)                                 as issued_value,
           count(m.txn_id)                              as issues,
           sum(m.quantity) / (j.quantity * n.need_per_piece) as issued_ratio
    from {{ ref('stg_erp__jobs') }} j
    join {{ ref('stg_erp__part_master') }} p using (part_number)
    join {{ ref('int_part_material_need') }} n using (part_number)
    left join {{ ref('stg_erp__material_transactions') }} m using (job_id)
    where n.jobs_measured >= 3
    group by 1, 2, 3, 4, 5, 6, 7

)

select
    job_id,
    part_number,
    material_spec,
    quantity,
    release_date,
    need_per_piece,
    issued_quantity,
    issued_value,
    issues,
    issued_ratio,
    case when issued_ratio >= 1.12 then 'charged another job''s material'
         else 'material used but never issued' end  as evidence,
    case when issued_ratio >= 1.12 then (issued_ratio - 1) * issued_value / issued_ratio
         else (1 - coalesce(issued_ratio, 0)) * issued_value / nullif(issued_ratio, 0) end as value_misstated,
    case when issued_ratio >= 1.3 or issued_ratio <= 0.7 or issued_ratio is null then 0.8
         else 0.55 end                               as confidence
from by_job
where issued_ratio >= 1.12 or issued_ratio <= 0.88 or issued_ratio is null
