-- T2: setup and run not separated. Before the labor codes went live the door
-- terminal offered one clock-on, so every record posted as run. Grain: one row per
-- work center and month, with the records and the share that carry the run code.

select
    work_center_id,
    date_trunc('month', clock_date)                 as month,
    count(*)                                        as records,
    sum(case when labor_type = 'run' then 1 else 0 end)   as run_records,
    sum(case when labor_type = 'setup' then 1 else 0 end) as setup_records,
    sum(hours)                                      as hours,
    sum(case when labor_type = 'run' then 1 else 0 end) / count(*) as run_share,
    after_codes
from {{ ref('stg_erp__labor_transactions') }}
where source = 'terminal' and labor_type <> 'indirect'
group by 1, 2, 8
having sum(case when labor_type = 'setup' then 1 else 0 end) = 0
