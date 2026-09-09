-- The in-progress variance flag replayed over every completed job at three
-- thresholds. The flag fires at the first point on the routing where the actual to
-- date runs more than the threshold over the estimate to date and at least the
-- minimum amount over: labor hours at an operation, material at issue. For a job
-- flagged while it was still open, the overrun after the flag is the actual less
-- the estimate on every operation that started after the flag, plus the material
-- and outside-processing variance in proportion to what was issued or received
-- after the flag date, net of what came in under estimate there.
-- Each sum is taken in a stated order, so a rebuild returns the same value to the
-- last digit. Grain: job, threshold.

{% set thresholds = [0.10, 0.15, 0.20] %}

with progress as (

    select * from {{ ref('int_job_op_progress') }}

),

jobs as (

    select s.job_id, s.release_year, s.completed_date, s.act_material, s.est_material_today, s.rate,
           s.c_material, s.c_outside, s.act_total_cost, s.est_cost_at_pool, p.ops, p.first_op_seq
    from {{ ref('mart_job_shortfall') }} s
    left join (select job_id, max(ops) as ops, min(op_seq) as first_op_seq from progress group by 1) p using (job_id)
    where s.status = 'completed'

),

material_issue as (

    select job_id, min(issue_date) as first_issue
    from {{ ref('stg_erp__material_transactions') }}
    where job_id is not null
    group by 1

),

labor_cross as (

    {% for t in thresholds %}
    select {{ t }} as threshold, job_id, op_index, op_seq, work_center_group, op_end,
           row_number() over (partition by job_id order by op_index) as rn
    from progress
    where cum_act_hours > (1 + {{ t }}) * cum_est_hours
      and cum_act_hours - cum_est_hours >= {{ var('inprogress_min_hours') }}
      and op_end is not null
    {% if not loop.last %}union all{% endif %}
    {% endfor %}

),

thresholds as (

    {% for t in thresholds %}select {{ t }} as threshold{% if not loop.last %} union all {% endif %}{% endfor %}

),

flags as (

    select t.threshold, j.job_id,
        -- material over estimate is visible at issue, before the first operation finishes
        j.act_material > (1 + t.threshold) * j.est_material_today
          and j.act_material - j.est_material_today >= {{ var('inprogress_min_dollars') }} as material_flag,
        cast(m.first_issue as timestamp)                                                  as material_flag_at,
        fl.op_index                                                                       as labor_op_index,
        fl.op_seq                                                                         as labor_op_seq,
        fl.work_center_group                                                              as labor_flag_cell,
        fl.op_end                                                                         as labor_flag_at
    from jobs j
    cross join thresholds t
    left join labor_cross fl on fl.job_id = j.job_id and fl.threshold = t.threshold and fl.rn = 1
    left join material_issue m on m.job_id = j.job_id

),

chosen as (

    select f.threshold, f.job_id, f.labor_flag_cell,
        f.material_flag and f.material_flag_at is not null
          and (f.labor_op_index is null or f.material_flag_at <= f.labor_flag_at)          as material_first,
        f.labor_op_index, f.labor_op_seq, f.material_flag_at, f.labor_flag_at
    from flags f

),

flagged as (

    select c.threshold, c.job_id, c.labor_flag_cell,
        case when c.material_first then 'material' when c.labor_op_index is not null then 'labor' end as flag_element,
        case when c.material_first then 1 else c.labor_op_index end                                  as flag_op_index,
        case when c.material_first then j.first_op_seq else c.labor_op_seq end                        as flag_operation_seq,
        case when c.material_first then c.material_flag_at else c.labor_flag_at end                   as flag_at,
        j.ops, j.completed_date, j.rate, j.c_material, j.c_outside, j.act_total_cost, j.est_cost_at_pool, j.release_year
    from chosen c
    join jobs j using (job_id)

),

-- what ran over, or under, after the flag
labor_after as (

    select f.threshold, f.job_id, sum((p.act_hours - p.est_hours) * f.rate order by p.op_index) as labor_after
    from flagged f
    join progress p on p.job_id = f.job_id and p.op_start > f.flag_at
    where f.flag_element is not null
    group by 1, 2

),

material_after as (

    select f.threshold, f.job_id,
           sum(case when m.issue_date > cast(f.flag_at as date) then m.quantity * m.unit_cost else 0 end
               order by m.issue_date, m.quantity * m.unit_cost)
             / nullif(sum(m.quantity * m.unit_cost order by m.issue_date, m.quantity * m.unit_cost), 0) as share_after
    from flagged f
    join {{ ref('stg_erp__material_transactions') }} m on m.job_id = f.job_id
    where f.flag_element is not null
    group by 1, 2

),

outside_after as (

    select f.threshold, f.job_id,
           sum(case when coalesce(o.receipt_date, o.order_date) > cast(f.flag_at as date) then o.amount else 0 end
               order by coalesce(o.receipt_date, o.order_date), o.amount)
             / nullif(sum(o.amount order by coalesce(o.receipt_date, o.order_date), o.amount), 0) as share_after
    from flagged f
    join {{ ref('int_osp_by_job') }} o on o.job_id = f.job_id
    where f.flag_element is not null
    group by 1, 2

)

select
    f.threshold,
    f.job_id,
    f.release_year,
    f.ops,
    f.flag_element,
    f.flag_op_index,
    f.flag_operation_seq,
    f.labor_flag_cell,
    f.flag_at,
    cast(f.flag_at as date)                                                                as flag_date,
    date_diff('day', cast(f.flag_at as date), f.completed_date)                            as days_before_ship,
    f.flag_element is not null                                                             as flagged,
    case when f.flag_element is null then null
         when f.flag_op_index = 1 then 'first operation'
         when f.flag_op_index >= f.ops then 'last operation'
         else 'a middle operation' end                                                     as flag_position,
    f.flag_element is not null and f.flag_op_index < f.ops                                 as flagged_with_operations_left,
    f.flag_element is not null and f.flag_op_index < f.ops
      and date_diff('day', cast(f.flag_at as date), f.completed_date) >= {{ var('inprogress_actionable_days') }} as flagged_while_open,
    f.flag_element is not null and f.act_total_cost <= f.est_cost_at_pool                  as recovered_by_close,
    f.act_total_cost - f.est_cost_at_pool                                                  as overrun,
    case when f.flag_element is not null and f.flag_op_index < f.ops
              and date_diff('day', cast(f.flag_at as date), f.completed_date) >= {{ var('inprogress_actionable_days') }}
         then coalesce(la.labor_after, 0)
            + f.c_material * coalesce(ma.share_after, 0)
            + f.c_outside * coalesce(oa.share_after, 0) end                                as overrun_after_flag
from flagged f
left join labor_after la using (threshold, job_id)
left join material_after ma using (threshold, job_id)
left join outside_after oa using (threshold, job_id)
order by f.threshold, f.job_id
