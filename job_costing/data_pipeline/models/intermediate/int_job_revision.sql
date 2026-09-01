-- Revision work on every job, whoever the customer: whether a revision was issued
-- after the job's release, when, and whether the work was billed as a change-order
-- line. Grain: job.

select
    job_id,
    customer_id,
    revision_changes_after_release > 0                                   as revision_after_release,
    revision_after_release_date,
    revision_changes_after_release > 0 and change_order_billed            as change_order_billed,
    case when revision_changes_after_release > 0 and change_order_billed
         then change_order_amount else 0 end                             as change_order_amount
from {{ ref('stg_erp__jobs') }}
