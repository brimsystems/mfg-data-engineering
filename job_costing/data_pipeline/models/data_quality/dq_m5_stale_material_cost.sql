-- M5: stale material cost in estimates. Quote lines (one row per line; the implied
-- price is the same at every quantity break) whose material estimate implies
-- a stock price below what the shop paid in the quote month, with the number of
-- months back the actual price last sat at the estimator's figure. Bar, plate, rod
-- and tube are priced per pound from the spec's monthly price; forgings and
-- castings per piece from the part's own issues.

with quotes as (

    select q.quote_id, q.line, q.part_number, q.quote_date, q.quantity, q.est_material, q.estimate_basis,
           p.material_spec, n.uom,
           q.est_material / nullif(q.quantity * n.need_per_piece, 0) as implied_unit_cost,
           date_trunc('month', q.quote_date) as quote_month
    from {{ ref('stg_erp__quotes') }} q
    join {{ ref('stg_erp__part_master') }} p using (part_number)
    join {{ ref('int_part_material_need') }} n using (part_number)
    where q.quote_date >= cast('{{ var("start_date") }}' as date)
      and q.break_seq = 1

),

-- per-piece stock: the part's own issue cost nearest the quote month
piece_price as (

    select q.quote_id, q.line, median(m.unit_cost) as actual_unit_cost
    from quotes q
    join {{ ref('stg_erp__jobs') }} j on j.part_number = q.part_number
    join {{ ref('stg_erp__material_transactions') }} m
      on m.job_id = j.job_id and m.quantity > 0
     and abs(date_diff('month', m.issue_date, q.quote_date)) <= 1
    where q.uom = 'ea'
    group by 1, 2

),

priced as (

    select q.*, coalesce(m.unit_cost, pp.actual_unit_cost) as actual_unit_cost,
           q.implied_unit_cost / coalesce(m.unit_cost, pp.actual_unit_cost) - 1 as gap_share
    from quotes q
    left join {{ ref('int_material_price_monthly') }} m
      on q.uom = 'lb' and m.material_spec = q.material_spec and m.uom = q.uom and m.month = q.quote_month
    left join piece_price pp using (quote_id, line)
    where coalesce(m.unit_cost, pp.actual_unit_cost) is not null

),

-- the last month, at or before the quote, when the actual price was at the estimator's figure
lag as (

    select p.quote_id, p.line, max(m.month) as price_matched_month
    from priced p
    join {{ ref('int_material_price_monthly') }} m
      on m.material_spec = p.material_spec and m.uom = p.uom and m.month <= p.quote_month
     and m.unit_cost <= p.implied_unit_cost * 1.02
    where p.uom = 'lb'
    group by 1, 2

)

select
    p.quote_id,
    p.line,
    p.part_number,
    p.material_spec,
    p.uom,
    p.estimate_basis,
    p.quote_date,
    p.quantity,
    p.est_material,
    p.implied_unit_cost,
    p.actual_unit_cost,
    p.gap_share,
    l.price_matched_month,
    date_diff('month', l.price_matched_month, p.quote_month) as lag_months
from priced p
left join lag l using (quote_id, line)
where p.gap_share < -0.05
