-- Outside-processing lines with the job they belong to: the job number on the line
-- where the buyer entered one, otherwise the engagement's attribution. An attributed
-- line is accepted only where its quantity is between half and twice the job's
-- quantity: a match by vendor, service and receipt window to a job of a very different
-- size is not that job's purchase order. Lines that could not be attributed, or that
-- fail the quantity guard, stay in the GL account and carry no job. A line invoiced at
-- the vendor's minimum charge is flagged, with what the minimum added over the
-- per-piece price times the pieces.

with attributed as (

    select a.po_id, a.job_id, a.method, a.confidence, a.confirmed_by,
           o.quantity between 0.5 * j.quantity and 2 * j.quantity as quantity_fits
    from {{ ref('stg_remediation__po_attribution') }} a
    join {{ ref('stg_erp__outside_processing') }} o using (po_id)
    join {{ ref('stg_erp__jobs') }} j on j.job_id = a.job_id
    where a.status = 'attributed'

)

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
    coalesce(o.job_id, case when a.quantity_fits then a.job_id end) as job_id,
    o.job_id                                              as erp_job_id,
    case when o.job_id is not null then 'job number on the purchase order'
         when a.quantity_fits then a.method
         when a.po_id is not null then 'residual in GL: attributed job is not of the line''s quantity'
         else 'residual in GL, not attributed' end        as source,
    case when o.job_id is not null then 1.0
         when a.quantity_fits then a.confidence else 0.0 end as confidence,
    case when a.quantity_fits then a.confirmed_by end     as confirmed_by,
    coalesce(a.po_id is not null and not a.quantity_fits and o.job_id is null, false) as failed_quantity_guard,
    v.vendor_minimum_charge,
    coalesce(o.invoice_amount = v.vendor_minimum_charge, false)                       as at_minimum,
    case when o.invoice_amount = v.vendor_minimum_charge
         then o.invoice_amount - o.quantity * o.unit_price else 0 end                 as minimum_excess
from {{ ref('stg_erp__outside_processing') }} o
left join {{ ref('stg_erp__vendors') }} v using (vendor_id)
left join attributed a on a.po_id = o.po_id
