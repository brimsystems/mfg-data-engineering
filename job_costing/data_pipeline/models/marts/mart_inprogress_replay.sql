-- The in-progress variance flag replayed over history at the threshold the job
-- cost screen uses: for every completed job, the first point on its routing where
-- the actual to date ran more than the threshold over the estimate to date (labor
-- hours by operation, material at issue), the operation and the date, how many days
-- before the job shipped, whether the job recovered by close, and what ran over
-- after the flag. This is what the shop could have known while the job was open,
-- not what it would have recovered. Grain: job.

select
    s.job_id, s.part_number, s.customer_id, s.customer_name, s.job_type, s.quantity, s.small_lot, s.infrequent_part, s.release_date,
    s.completed_date, s.due_date, s.release_year, s.price, s.contribution, s.margin_on_price, s.coverage,
    s.change_order_customer, s.revision_after_release, s.first_after_revision, s.hard_alloy,
    f.overrun,
    f.ops, f.flag_element, f.flag_op_index, f.flag_operation_seq, f.labor_flag_cell, f.flag_at, f.flag_date, f.days_before_ship,
    f.flagged,
    f.flag_position,
    s.completed_date > s.due_date                                                           as shipped_late,
    f.flagged_with_operations_left,
    f.flagged_while_open,
    f.recovered_by_close,
    f.overrun_after_flag
from {{ ref('int_inprogress_flag') }} f
join {{ ref('mart_job_shortfall') }} s using (job_id)
where f.threshold = {{ var('inprogress_threshold') }}
