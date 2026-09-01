-- The rate to cost an hour on each work center in each year: the blended shop
-- rate the ERP applied, and the engagement's pool rate indexed to the shop
-- rate history so history is costed at the level of its own year.

with years as (

    select distinct extract(year from effective_date) as year, max(blended_rate) over (partition by effective_date) as blended_rate
    from {{ ref('stg_erp__work_center_rates') }}

),

latest as (

    select max(blended_rate) as blended_rate_now from {{ ref('stg_erp__work_center_rates') }}
    where effective_date = (select max(effective_date) from {{ ref('stg_erp__work_center_rates') }})

)

select
    p.work_center_id,
    y.year,
    y.blended_rate,
    p.labor_rate,
    p.burden_rate,
    p.attended_ratio,
    p.pool_rate * y.blended_rate / l.blended_rate_now as pool_rate
from {{ ref('stg_remediation__rate_pools') }} p
cross join years y
cross join latest l
