-- The shortfall on each job by cause, one row per job and cause, with the job's
-- primary cause (the largest assigned amount) and the action it maps to. Offsets
-- (elements that came in under estimate) and the amount no cause explains are kept
-- as rows of their own so a job's rows add back to its shortfall.
-- Grain: job, cause.

with s as (

    select * from {{ ref('mart_job_shortfall') }}

),

long as (

    select job_id, cause, amount from s
    unpivot (amount for cause in (
        cause_standing_price, cause_quoted_price, cause_list_price, cause_revision_work_unbilled,
        cause_first_run_after_revision, cause_infrequent_part_setup, cause_interrupted_second_setup,
        cause_hard_alloy_run_allowance, cause_older_machine, cause_standard_below_cycle,
        cause_osp_vendor_minimum, cause_vendor_price, cause_osp_allocated, cause_material, cause_scrap_rework, not_attributable, offsets))

),

labelled as (

    select job_id, cause as cause_code, amount,
        case cause
            when 'cause_standing_price'           then 'Standing price below target'
            when 'cause_quoted_price'             then 'Quoted below target'
            when 'cause_list_price'               then 'List price below target'
            when 'cause_revision_work_unbilled'   then 'Revision work not billed'
            when 'cause_first_run_after_revision' then 'First run after a revision'
            when 'cause_infrequent_part_setup'    then 'New or infrequent part setup, mill-turn and 5-axis'
            when 'cause_interrupted_second_setup' then 'Interrupted job, second setup'
            when 'cause_hard_alloy_run_allowance' then 'Hard-alloy run allowance'
            when 'cause_older_machine'            then 'Run on an older vertical mill'
            when 'cause_standard_below_cycle'     then 'Routing standard below the measured cycle'
            when 'cause_osp_vendor_minimum'       then 'Outside processing at a vendor minimum'
            when 'cause_vendor_price'             then 'Vendor prices above the estimate'
            when 'cause_osp_allocated'            then 'Outside processing allocated from the ledger'
            when 'cause_material'                 then 'Material over estimate'
            when 'cause_scrap_rework'             then 'Scrap and rework'
            when 'not_attributable'               then 'Not attributable'
            when 'offsets'                        then 'Elements under estimate'
        end as cause,
        case cause
            when 'cause_standing_price'           then 'Reprice the part'
            when 'cause_list_price'               then 'Reprice the part'
            when 'cause_quoted_price'             then 'Correct the quote'
            when 'cause_infrequent_part_setup'    then 'Correct the quote'
            when 'cause_first_run_after_revision' then 'Correct the quote'
            when 'cause_osp_vendor_minimum'       then 'Correct the quote'
            when 'cause_interrupted_second_setup' then 'Process fix'
            when 'cause_vendor_price'             then 'Correct the quote'
            when 'cause_osp_allocated'            then 'Accept'
            when 'cause_revision_work_unbilled'   then 'Bill the change order'
            when 'cause_hard_alloy_run_allowance' then 'Correct the routing standard'
            when 'cause_standard_below_cycle'     then 'Correct the routing standard'
            when 'cause_older_machine'            then 'Process fix'
            when 'cause_scrap_rework'             then 'Process fix'
            when 'cause_material'                 then 'Process fix'
            when 'not_attributable'               then 'Accept'
        end as action
    from long

),

ranked as (

    select l.*,
           row_number() over (partition by l.job_id
                              order by case when l.cause_code = 'offsets' then 1 else 0 end, l.amount desc, l.cause_code) as cause_rank
    from labelled l

)

select job_id, cause_code, cause, action, amount, cause_rank,
       cause_rank = 1 and cause_code <> 'offsets' and amount > 0 as is_primary
from ranked
