-- The repeat-part repricing queue: every repeat part with its standing price,
-- current cost at today's prices, rates and measured standards, implied margin,
-- what moved since the part was last quoted, the dollar gap to target on annual
-- volume, and the decision taken in the engagement's review where there was one.

with last_job as (

    select part_number, max(release_date) as last_release, count(*) as jobs_36m
    from {{ ref('stg_erp__jobs') }} group by 1

),

realized as (

    select part_number, sum(contribution) / nullif(sum(price), 0) as realized_margin_on_price, sum(price) as revenue_36m
    from {{ ref('mart_margin_by_job') }} group by 1

)

select
    c.part_number,
    c.part_family,
    c.customer_id,
    cu.customer_name,
    c.material_spec,
    c.first_quote_date,
    c.standing_price,
    c.standing_price_date,
    c.typical_lot,
    c.annual_volume,
    lj.jobs_36m,
    lj.last_release,
    c.material_per_piece_current,
    c.labor_per_piece_current,
    c.osp_per_piece_current,
    c.current_unit_cost,
    c.target_price,
    c.margin_on_price                                                as implied_margin_on_price,
    c.markup_on_current_cost,
    r.realized_margin_on_price,
    r.revenue_36m,
    c.gap_to_target_annual,
    c.quote_date_earliest                                            as last_quote_date,
    c.quote_cost_per_piece                                           as quoted_unit_cost,
    c.moved_material,
    c.moved_rate,
    c.moved_standard,
    c.moved_outside,
    c.any_standard_refreshed,
    d.decision,
    d.new_price,
    d.rationale,
    d.decided_by,
    d.decision_date,
    c.standing_price < c.target_price                                as below_target,
    c.standing_price < c.current_unit_cost                           as below_cost,
    ntile(4) over (order by c.margin_on_price)                       as margin_quartile
from {{ ref('int_current_cost') }} c
left join {{ ref('stg_erp__customers') }} cu using (customer_id)
left join last_job lj using (part_number)
left join realized r using (part_number)
left join {{ ref('stg_remediation__repricing_decisions') }} d using (part_number)
where c.part_type = 'repeat'
