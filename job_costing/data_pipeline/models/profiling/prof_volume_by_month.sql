-- What the shop did each month: jobs released, revenue, clocked hours, machine
-- in-cycle hours, material issued and outside processing ordered.

with months as (

    select distinct date_trunc('month', release_date) as month from {{ ref('stg_erp__jobs') }}

),

jobs as (

    select date_trunc('month', release_date) as month, count(*) as jobs_released, sum(price) as revenue_released,
           sum(case when job_type = 'repeat' then price end) as revenue_repeat,
           sum(case when job_type = 'new' then price end) as revenue_new,
           sum(case when job_type = 'own_product' then price end) as revenue_own_product
    from {{ ref('stg_erp__jobs') }} group by 1

),

labor as (

    select date_trunc('month', clock_date) as month, sum(hours) as clocked_hours, count(*) as clock_records
    from {{ ref('stg_erp__labor_transactions') }} group by 1

),

machine as (

    select date_trunc('month', interval_date) as month,
           sum(case when state = 'in_cycle' then hours end) as in_cycle_hours,
           sum(case when state = 'setup' then hours end) as setup_hours
    from {{ ref('stg_monitoring__machine_monitoring') }} group by 1

),

material as (

    select date_trunc('month', issue_date) as month, sum(value) as material_issued
    from {{ ref('stg_erp__material_transactions') }} group by 1

),

osp as (

    select date_trunc('month', order_date) as month, count(*) as po_lines, sum(quantity * unit_price) as outside_ordered
    from {{ ref('stg_erp__outside_processing') }} group by 1

)

select m.month, j.jobs_released, j.revenue_released, j.revenue_repeat, j.revenue_new, j.revenue_own_product,
       l.clocked_hours, l.clock_records, mc.in_cycle_hours, mc.setup_hours, mt.material_issued, o.po_lines, o.outside_ordered
from months m
left join jobs j using (month)
left join labor l using (month)
left join machine mc using (month)
left join material mt using (month)
left join osp o using (month)
order by 1
