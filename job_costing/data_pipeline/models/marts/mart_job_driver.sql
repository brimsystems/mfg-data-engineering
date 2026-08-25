-- The driver of each completed job's variance, assigned by rule, not by judgment. Each
-- rule is a test on the job variance mart with its threshold in the project vars; every
-- rule that fires carries the dollar variance behind it. The driver is the firing rule
-- with the largest dollars and the second driver the next. A job where no rule fires, or
-- where the largest firing rule carries less than driver_min_share of the job's overrun,
-- is not attributable. The same model feeds the job variance report and the diagnostic's
-- loss-job table. Grain: completed job.
--
--   Routing standard            run ratio > driver_run_ratio and the part's other jobs completed in the
--                               trailing twelve months ran over their run estimate too
--   Small-lot setup             setup ratio > driver_setup_ratio and lot under the small-lot threshold
--   Unbilled revision work      labor hours over estimate, a revision change after release, no change order billed
--   Vendor rate                 outside processing > driver_vendor_ratio x estimate
--   Scrap and rework            scrap plus rework cost > driver_scrap_share x estimated cost
--   Material                    material over estimate by more than driver_material_share
--   Priced below estimated cost the job's own estimate showed a loss before it started, sized as the loss
--                               the estimate promised, so it competes on dollars with any overrun on the same job

with v as (

    select * from {{ ref('mart_job_variance') }}

),

-- the part's other jobs completed in the twelve months to this one: did they run over too?
part_history as (

    select a.job_id, median(b.ratio_run) as other_jobs_run_ratio, count(b.job_id) as other_jobs
    from v a
    join v b
      on b.part_number = a.part_number and b.job_id <> a.job_id
     and b.completed_date <= a.completed_date and b.completed_date > a.completed_date - interval 365 day
     and b.ratio_run is not null
    group by 1

),

rules as (

    select v.job_id, v.overrun, ph.other_jobs_run_ratio,
        case when v.ratio_run > {{ var('driver_run_ratio') }} and ph.other_jobs_run_ratio > 1.0 then v.var_run end                        as d_standard,
        case when v.ratio_setup > {{ var('driver_setup_ratio') }} and v.quantity < {{ var('small_lot_threshold') }} then v.var_setup end   as d_small_lot,
        case when v.act_setup_hours + v.act_run_hours > v.est_setup_hours + v.est_run_hours
              and v.revision_changes_after_release > 0 and not v.change_order_billed then v.var_setup + v.var_run end                   as d_revision,
        case when v.est_outside > 0 and v.act_outside > {{ var('driver_vendor_ratio') }} * v.est_outside then v.var_outside end           as d_vendor,
        case when v.act_scrap_rework > {{ var('driver_scrap_share') }} * v.est_total then v.act_scrap_rework end                          as d_scrap,
        case when v.var_material > {{ var('driver_material_share') }} * v.est_material then v.var_material end                            as d_material,
        case when v.est_margin < 0 then -v.est_margin * v.price end                                                                    as d_price
    from v
    left join part_history ph using (job_id)

),

fired as (

    select job_id, overrun, driver, amount,
           row_number() over (partition by job_id order by amount desc, driver) as rn
    from (
        select job_id, overrun, 'Routing standard' as driver, d_standard as amount from rules where d_standard is not null
        union all select job_id, overrun, 'Small-lot setup', d_small_lot from rules where d_small_lot is not null
        union all select job_id, overrun, 'Unbilled revision work', d_revision from rules where d_revision is not null
        union all select job_id, overrun, 'Vendor rate', d_vendor from rules where d_vendor is not null
        union all select job_id, overrun, 'Scrap and rework', d_scrap from rules where d_scrap is not null
        union all select job_id, overrun, 'Material', d_material from rules where d_material is not null
        union all select job_id, overrun, 'Priced below estimated cost', d_price from rules where d_price is not null
    )

),

top2 as (

    select job_id,
           max(case when rn = 1 then driver end) as first_driver,  max(case when rn = 1 then amount end) as first_amount,
           max(case when rn = 2 then driver end) as second_driver, max(case when rn = 2 then amount end) as second_amount,
           count(*) as rules_fired,
           max(overrun) as overrun
    from fired
    group by 1

),

assigned as (

    select v.job_id, v.part_number, v.customer_id, v.job_type, v.completed_date, v.release_date,
        coalesce(t.rules_fired, 0) as rules_fired,
        case when t.first_driver is null then 'Not attributable'
             when t.first_driver <> 'Priced below estimated cost' and t.first_amount < {{ var('driver_min_share') }} * t.overrun then 'Not attributable'
             else t.first_driver end                                                                    as driver,
        case when t.first_driver is null then null
             when t.first_driver <> 'Priced below estimated cost' and t.first_amount < {{ var('driver_min_share') }} * t.overrun then null
             else t.first_amount end                                                                    as driver_variance,
        case when t.first_driver is not null and t.first_driver <> 'Priced below estimated cost'
              and t.first_amount < {{ var('driver_min_share') }} * t.overrun then t.first_driver
             else t.second_driver end                                                                   as second_driver,
        case when t.first_driver is not null and t.first_driver <> 'Priced below estimated cost'
              and t.first_amount < {{ var('driver_min_share') }} * t.overrun then t.first_amount
             else t.second_amount end                                                                   as second_variance
    from v
    left join top2 t using (job_id)

),

-- what has been decided about each driver, for the action status column
std as (

    select part_number, min(effective_date) as refreshed_on,
           bool_or(reviewer_decision in ('accepted', 'disputed, adjusted')) as refreshed,
           bool_and(reviewer_decision = 'disputed, standard kept') as kept
    from {{ ref('stg_remediation__standard_update_log') }}
    group by 1

),

acts as (

    select action_id, decision_date from {{ ref('stg_remediation__engagement_actions') }}

),

queue as (

    select part_number, decision, new_price, rationale, below_target from {{ ref('mart_repricing_queue') }}

),

t8 as (

    select distinct job_id from {{ ref('dq_t8_material_wrong_job') }}

)

select
    a.*,
    case a.driver
        when 'Routing standard'             then 'Correct the routing standard'
        when 'Small-lot setup'              then 'Correct the quote'
        when 'Unbilled revision work'       then 'Bill the change order'
        when 'Vendor rate'                  then 'Correct the quote'
        when 'Scrap and rework'             then 'Process fix'
        when 'Material'                     then 'Process fix'
        when 'Priced below estimated cost' then case when a.job_type = 'new' then 'Correct the quote' else 'Reprice the part' end
        else 'Accept' end                                                                               as action,
    case a.driver
        when 'Routing standard' then
            case when a.job_type = 'new' then 'New part: standard set at quote'
                 when st.refreshed and st.refreshed_on <= cast('{{ var("end_date") }}' as date) then 'Standard refreshed ' || strftime(st.refreshed_on, '%m/%d/%Y')
                 when st.kept then 'Standard kept after dispute'
                 else 'Standard not measured on the machines' end
        when 'Small-lot setup' then 'Quoted at first-article setup from ' || strftime((select decision_date from acts where action_id = 'A6'), '%m/%d/%Y')
        when 'Unbilled revision work' then
            case when a.release_date < (select decision_date from acts where action_id = 'A7') then 'Back-billing declined'
                 else 'Change order not raised' end
        when 'Vendor rate' then 'Current vendor price in quoting from ' || strftime((select decision_date from acts where action_id = 'A4'), '%m/%d/%Y')
        when 'Scrap and rework' then 'Monthly scrap reason review'
        when 'Material' then case when t8.job_id is not null then 'Issue corrected to part need' else 'Stockroom review' end
        when 'Priced below estimated cost' then
            case when a.job_type = 'own_product' then 'List to target at next price list'
                 when a.job_type = 'new' then 'Quoted below target'
                 when q.decision = 'reprice' then 'Repriced to $' || cast(round(q.new_price, 2) as varchar)
                 when q.decision = 'hold' then 'Held: ' || q.rationale
                 when q.decision = 'exit' then 'Exit at next release'
                 else 'Standing price now at target' end
        else 'Accepted' end                                                                             as action_status
from assigned a
left join std st on st.part_number = a.part_number
left join queue q on q.part_number = a.part_number
left join t8 on t8.job_id = a.job_id
