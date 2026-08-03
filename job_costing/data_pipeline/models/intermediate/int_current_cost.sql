-- Current unit cost of every repeat part and own product at today's material
-- prices, the work-center rate pools and the measured standards, over the part's
-- typical lot, against the standing price. Also what the estimator saw at the
-- part's earliest quote line so the movement can be split by element.

with parts as (

    select p.part_number, p.part_type, p.part_family, p.customer_id, p.material_spec,
           coalesce(p.standing_price, p.list_price) as standing_price, p.standing_price_date, p.first_quote_date
    from {{ ref('stg_erp__part_master') }} p
    where p.part_type in ('repeat', 'own_product')

),

lots as (

    select part_number,
           median(quantity)                                                                                    as typical_lot,
           count(*)                                                                                            as jobs_in_window,
           sum(case when release_date > cast('{{ var("end_date") }}' as date) - interval 12 month then quantity else 0 end) as annual_volume,
           max(release_date)                                                                                   as last_release
    from {{ ref('stg_erp__jobs') }}
    group by 1

),

standards as (

    select r.part_number, r.op_seq, r.work_center_id,
           r.std_setup_hours, r.std_run_min_per_piece,
           coalesce(s.new_std_setup_hours, r.std_setup_hours)      as cur_setup_hours,
           coalesce(s.new_std_run_min, r.std_run_min_per_piece)    as cur_run_min_per_piece,
           s.reviewer_decision
    from {{ ref('stg_erp__routings') }} r
    left join {{ ref('stg_remediation__standard_update_log') }} s using (part_number, op_seq)

),

pools as (

    select work_center_id, pool_rate from {{ ref('stg_remediation__rate_pools') }}

),

blended as (

    select max(blended_rate) as blended_rate_now from {{ ref('stg_erp__work_center_rates') }}
    where effective_date = (select max(effective_date) from {{ ref('stg_erp__work_center_rates') }})

),

labor as (

    select s.part_number,
           sum(s.cur_setup_hours + s.cur_run_min_per_piece / 60.0 * l.typical_lot)                           as cur_hours_per_lot,
           sum(s.std_setup_hours + s.std_run_min_per_piece / 60.0 * l.typical_lot)                           as std_hours_per_lot,
           sum((s.cur_setup_hours + s.cur_run_min_per_piece / 60.0 * l.typical_lot) * p.pool_rate)           as cur_labor_per_lot,
           sum((s.std_setup_hours + s.std_run_min_per_piece / 60.0 * l.typical_lot) * p.pool_rate)           as std_labor_per_lot_pool,
           sum((s.std_setup_hours + s.std_run_min_per_piece / 60.0 * l.typical_lot) * b.blended_rate_now)    as std_labor_per_lot_blended,
           bool_or(s.reviewer_decision is not null)                                                          as any_standard_refreshed
    from standards s
    join lots l using (part_number)
    join pools p using (work_center_id)
    cross join blended b
    group by 1

),

material as (

    select n.part_number, n.need_per_piece * c.unit_cost_current as material_per_piece_current, c.unit_cost_current, n.need_per_piece
    from {{ ref('int_part_material_need') }} n
    join parts p using (part_number)
    join {{ ref('int_material_price_current') }} c on c.material_spec = p.material_spec and c.uom = n.uom

),

-- the latest purchase-order price per service on the part's jobs
osp as (

    select part_number, sum(unit_price) as osp_per_piece_current
    from (
        select j.part_number, o.service_type, o.unit_price,
               row_number() over (partition by j.part_number, o.service_type order by o.order_date desc) as rn
        from {{ ref('int_osp_by_job') }} o
        join {{ ref('stg_erp__jobs') }} j using (job_id)
    )
    where rn = 1
    group by 1

),

-- the earliest quote line the quoting module holds for the part, at the quantity break nearest the typical lot
first_quote as (

    select part_number, quote_date as quote_date_earliest, quantity as quoted_lot,
           est_material / quantity as quote_material_per_piece,
           (est_setup_hours + est_run_hours) / quantity as quote_hours_per_piece,
           est_outside / quantity as quote_osp_per_piece,
           est_total_cost / quantity as quote_cost_per_piece,
           quoted_price                as quoted_unit_price
    from (
        select q.*, row_number() over (partition by q.part_number order by q.quote_date, q.quote_id, abs(ln(q.quantity / l.typical_lot))) as rn
        from {{ ref('stg_erp__quotes') }} q
        join lots l using (part_number)
    )
    where rn = 1

)

select
    p.part_number,
    p.part_type,
    p.part_family,
    p.customer_id,
    p.material_spec,
    p.standing_price,
    p.standing_price_date,
    p.first_quote_date,
    l.typical_lot,
    l.annual_volume,
    l.jobs_in_window,
    l.last_release,
    m.need_per_piece,
    m.unit_cost_current                                                        as material_unit_cost_current,
    m.material_per_piece_current,
    lb.cur_hours_per_lot / l.typical_lot                                       as hours_per_piece_current,
    lb.std_hours_per_lot / l.typical_lot                                       as hours_per_piece_erp_standard,
    lb.cur_labor_per_lot / l.typical_lot                                       as labor_per_piece_current,
    lb.std_labor_per_lot_pool / l.typical_lot                                  as labor_per_piece_erp_standard_pool,
    lb.std_labor_per_lot_blended / l.typical_lot                               as labor_per_piece_erp_standard_blended,
    lb.any_standard_refreshed,
    coalesce(o.osp_per_piece_current, 0)                                       as osp_per_piece_current,
    m.material_per_piece_current + lb.cur_labor_per_lot / l.typical_lot + coalesce(o.osp_per_piece_current, 0) as current_unit_cost,
    (m.material_per_piece_current + lb.cur_labor_per_lot / l.typical_lot + coalesce(o.osp_per_piece_current, 0)) * (1 + {{ var('target_markup') }}) as target_price,
    p.standing_price / nullif(m.material_per_piece_current + lb.cur_labor_per_lot / l.typical_lot + coalesce(o.osp_per_piece_current, 0), 0) - 1 as markup_on_current_cost,
    1 - (m.material_per_piece_current + lb.cur_labor_per_lot / l.typical_lot + coalesce(o.osp_per_piece_current, 0)) / nullif(p.standing_price, 0) as margin_on_price,
    greatest(0, (m.material_per_piece_current + lb.cur_labor_per_lot / l.typical_lot + coalesce(o.osp_per_piece_current, 0)) * (1 + {{ var('target_markup') }}) - p.standing_price) * l.annual_volume as gap_to_target_annual,
    q.quote_date_earliest,
    q.quoted_lot,
    q.quote_material_per_piece,
    q.quote_hours_per_piece,
    q.quote_osp_per_piece,
    q.quote_cost_per_piece,
    q.quoted_unit_price,
    -- what moved since that quote, per piece
    m.material_per_piece_current - q.quote_material_per_piece                                    as moved_material,
    (lb.cur_hours_per_lot / l.typical_lot - q.quote_hours_per_piece) * (lb.cur_labor_per_lot / nullif(lb.cur_hours_per_lot, 0)) as moved_standard,
    q.quote_hours_per_piece * (lb.cur_labor_per_lot / nullif(lb.cur_hours_per_lot, 0)) - (q.quote_cost_per_piece - q.quote_material_per_piece - q.quote_osp_per_piece) as moved_rate,
    coalesce(o.osp_per_piece_current, 0) - q.quote_osp_per_piece                                 as moved_outside
from parts p
join lots l using (part_number)
join labor lb using (part_number)
join material m using (part_number)
left join osp o using (part_number)
left join first_quote q using (part_number)
