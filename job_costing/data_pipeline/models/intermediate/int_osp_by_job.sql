-- Outside-processing lines with the job they belong to: the job number on the line
-- where the buyer entered one, otherwise the engagement's attribution. Lines that
-- could not be attributed stay in the GL account and carry no job.

select
    o.po_id,
    o.line,
    o.vendor_id,
    o.service_type,
    o.description,
    o.quantity,
    o.unit_price,
    o.order_date,
    o.receipt_date,
    coalesce(o.invoice_amount, o.quantity * o.unit_price) as amount,
    o.invoice_amount is not null                          as invoiced,
    coalesce(o.job_id, a.job_id)                          as job_id,
    o.job_id                                              as erp_job_id,
    case when o.job_id is not null then 'job number on the purchase order'
         when a.job_id is not null then a.method
         else 'residual in GL, not attributed' end        as source,
    case when o.job_id is not null then 1.0 else coalesce(a.confidence, 0.0) end as confidence,
    a.confirmed_by
from {{ ref('stg_erp__outside_processing') }} o
left join {{ ref('stg_remediation__po_attribution') }} a
  on a.po_id = o.po_id and a.status = 'attributed'
