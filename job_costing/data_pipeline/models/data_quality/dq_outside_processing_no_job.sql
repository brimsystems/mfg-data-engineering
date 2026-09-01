-- Outside processing not tied to jobs. Purchase-order lines coded to the
-- outside-processing GL account with no job number.

select
    o.po_id,
    o.line,
    o.vendor_id,
    o.service_type,
    o.gl_account,
    o.description,
    o.description_part_number,
    o.quantity,
    o.unit_price,
    o.order_date,
    o.after_config,
    a.job_id                                        as attributed_job_id,
    a.method                                        as attribution_method,
    a.confidence                                    as attribution_confidence,
    case when o.description_part_number is not null then 'part number in the description'
         else 'generic description' end             as evidence
from {{ ref('stg_erp__outside_processing') }} o
left join {{ ref('stg_remediation__po_attribution') }} a on a.po_id = o.po_id and a.status = 'attributed'
where o.job_id is null
