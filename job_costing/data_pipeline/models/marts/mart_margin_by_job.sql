-- The corrected job cost with the dimensions the margin analysis cuts by. One
-- row per job (cleaned history and restructured engagement-period jobs).

with primary_cell as (

    select job_id, left(work_center_id, 3) as primary_work_center_group
    from (
        select job_id, work_center_id, row_number() over (partition by job_id order by sum(hours) desc, work_center_id) as rn
        from {{ ref('int_labor_hours_by_job') }}
        group by 1, 2
    )
    where rn = 1

),

blended_cost as (

    -- the same hours at the blended shop rate, for the comparison of the two rate bases
    select h.job_id, sum((h.setup_hours + h.run_hours + h.rework_hours) * r.blended_rate) as act_labor_blended
    from {{ ref('int_labor_hours_by_job') }} h
    join {{ ref('stg_erp__jobs') }} j using (job_id)
    join {{ ref('int_rates') }} r on r.work_center_id = h.work_center_id and r.year = extract(year from j.release_date)
    group by 1

),

-- how recently the shop last ran the part, from its own job history: a part with no earlier job
-- is new if it is quoted work, and not run in a year if the history already covers a year
part_history as (

    select job_id,
        date_diff('day', lag(release_date) over (partition by part_number order by release_date, job_id), release_date) as days_since_part_ran,
        date_diff('day', cast('{{ var("start_date") }}' as date), release_date)                                              as days_into_history,
        job_type
    from {{ ref('stg_erp__jobs') }}

)

select
    f.*,
    p.part_family,
    p.material_spec,
    p.part_type,
    coalesce(c.customer_name, 'Own products, to stock')          as customer_name,
    coalesce(c.industry, 'Own products')                          as industry,
    date_trunc('month', f.release_date)                              as release_month,
    extract(year from f.release_date)                                as release_year,
    case when f.quantity < 10 then '1-9'
         when f.quantity < 25 then '10-24'
         when f.quantity < 50 then '25-49'
         when f.quantity < 100 then '50-99'
         when f.quantity < 250 then '100-249'
         else '250+' end                                             as lot_band,
    f.quantity < {{ var('small_lot_threshold') }}                    as small_lot,
    ph.days_since_part_ran,
    case when ph.days_since_part_ran is null
         then ph.job_type = 'new' or ph.days_into_history > {{ var('infrequent_part_days') }}
         else ph.days_since_part_ran > {{ var('infrequent_part_days') }} end as infrequent_part,
    pc.primary_work_center_group,
    b.act_labor_blended,
    f.act_total_cost - f.act_labor + b.act_labor_blended             as act_total_cost_blended,
    (f.price - (f.act_total_cost - f.act_labor + b.act_labor_blended)) / nullif(f.price, 0) as margin_on_price_blended,
    f.act_setup_hours / nullif(f.est_setup_hours, 0)                 as setup_hours_ratio,
    f.act_run_hours / nullif(f.est_run_hours, 0)                     as run_hours_ratio,
    f.act_labor_hours / nullif(f.est_setup_hours + f.est_run_hours, 0) as labor_hours_ratio
from {{ ref('fct_job_cost') }} f
join {{ ref('stg_erp__part_master') }} p using (part_number)
left join {{ ref('stg_erp__customers') }} c on c.customer_id = f.customer_id
left join primary_cell pc using (job_id)
left join blended_cost b using (job_id)
left join part_history ph using (job_id)
where f.version <> 'raw'
