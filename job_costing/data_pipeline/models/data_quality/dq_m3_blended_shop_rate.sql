-- M3: one blended shop rate. Every work center carries the same labor and burden
-- rate on every effective date, refreshed once a year, whatever the machine.

with by_date as (

    select effective_date,
           count(distinct work_center_id) as work_centers,
           count(distinct blended_rate)   as distinct_rates,
           max(blended_rate)              as blended_rate
    from {{ ref('stg_erp__work_center_rates') }}
    group by 1

)

select
    r.work_center_id,
    w.work_center_type,
    r.effective_date,
    r.labor_rate,
    r.burden_rate,
    r.blended_rate,
    r.attended_ratio,
    d.distinct_rates                                as distinct_rates_on_date,
    d.work_centers                                  as work_centers_on_date,
    p.pool_rate                                     as engagement_pool_rate,
    p.pool_rate / r.blended_rate - 1                as pool_vs_blended_share
from {{ ref('stg_erp__work_center_rates') }} r
join by_date d using (effective_date)
join {{ ref('stg_erp__work_centers') }} w using (work_center_id)
left join {{ ref('stg_remediation__rate_pools') }} p using (work_center_id)
where d.distinct_rates = 1
