-- The in-progress variance flag replayed over history: for every completed job,
-- the first point on its routing where the actual to date ran more than the
-- threshold over the estimate to date (labor hours by operation, material at
-- issue), how far down the routing that was and how many days before the job
-- shipped. Each flagged job is grouped by what the shop could have done with the
-- warning. This is what the shop could have known while the job was open, not
-- what it would have recovered. Grain: job.

with progress as (

    select * from {{ ref('int_job_op_progress') }}

),

labor_cross as (

    select job_id, op_index, work_center_group, op_end,
           row_number() over (partition by job_id order by op_index) as rn
    from progress
    where cum_act_hours > (1 + {{ var('inprogress_threshold') }}) * cum_est_hours
      and cum_act_hours - cum_est_hours >= {{ var('inprogress_min_hours') }}
      and op_end is not null

),

first_labor as (

    select * from labor_cross where rn = 1

),

material_issue as (

    select job_id, min(issue_date) as first_issue
    from {{ ref('stg_erp__material_transactions') }}
    where job_id is not null
    group by 1

),

jobs as (

    select s.*, p.ops
    from {{ ref('mart_job_shortfall') }} s
    left join (select job_id, max(ops) as ops from progress group by 1) p using (job_id)
    where s.status = 'completed'

),

flags as (

    select j.job_id,
        -- material over estimate is visible at issue, before the first operation finishes
        j.act_material > (1 + {{ var('inprogress_threshold') }}) * j.est_material_today
          and j.act_material - j.est_material_today >= {{ var('inprogress_min_dollars') }} as material_flag,
        cast(m.first_issue as timestamp)                                                  as material_flag_at,
        fl.op_index                                                                       as labor_op_index,
        fl.work_center_group                                                              as labor_flag_cell,
        fl.op_end                                                                         as labor_flag_at
    from jobs j
    left join first_labor fl using (job_id)
    left join material_issue m using (job_id)

),

first_flag as (

    select f.job_id, f.labor_flag_cell,
        f.material_flag and f.material_flag_at is not null
          and (f.labor_op_index is null or f.material_flag_at <= f.labor_flag_at)          as material_first
    from flags f

),

chosen as (

    select ff.job_id, ff.labor_flag_cell,
        case when ff.material_first then 'material' when f.labor_op_index is not null then 'labor' end as flag_element,
        case when ff.material_first then 1 else f.labor_op_index end                                  as flag_op_index,
        case when ff.material_first then f.material_flag_at else f.labor_flag_at end                   as flag_at
    from first_flag ff
    join flags f using (job_id)

),

scored as (

    select j.*, c.flag_element, c.flag_op_index, c.labor_flag_cell, c.flag_at,
           date_diff('day', cast(c.flag_at as date), j.completed_date) as days_before_ship
    from jobs j
    left join chosen c using (job_id)

)

select
    job_id, part_number, customer_id, customer_name, job_type, quantity, small_lot, release_date,
    completed_date, due_date, release_year, price, contribution, margin_on_price, coverage,
    change_order_customer, first_after_revision, difficult_alloy,
    act_total_cost - est_cost_at_pool                                                       as overrun,
    ops, flag_element, flag_op_index, labor_flag_cell, flag_at, days_before_ship,
    flag_element is not null                                                                as flagged,
    completed_date > due_date                                                               as shipped_late,
    flag_element is not null and flag_op_index < ops
      and days_before_ship >= {{ var('inprogress_actionable_days') }}                         as flagged_while_open,
    case
        when flag_element is null then null
        when not (flag_op_index < ops and days_before_ship >= {{ var('inprogress_actionable_days') }})
             then 'Nothing: flagged too late'
        when change_order_customer then 'Change order billed'
        when completed_date > due_date then 'Expedite avoided'
        when small_lot or first_after_revision then 'Quantity or scope discussed'
        else 'Nothing: no lever while open'
    end                                                                                     as lever
from scored
