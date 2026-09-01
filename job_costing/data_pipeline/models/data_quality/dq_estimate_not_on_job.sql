-- Estimate not attached to the job. Jobs carrying no estimate by element
-- although the quoting module holds a quote for the part. Every job before the
-- configuration change on {{ var('estimate_to_job_date') }}.

with quoted as (

    select part_number, count(*) as quote_lines, max(quote_date) as last_quote_date
    from {{ ref('stg_erp__quotes') }}
    group by 1

)

select
    j.job_id,
    j.part_number,
    j.job_type,
    j.release_date,
    j.quote_id,
    q.quote_lines,
    q.last_quote_date,
    case when j.quote_id is not null then 'won quote linked, estimate not carried'
         when q.quote_lines > 0 then 'part quoted, no quote linked to the job'
         when j.job_type = 'own_product' then 'own product, standard cost not carried'
         else 'no quote line for the part' end as evidence
from {{ ref('stg_erp__jobs') }} j
left join quoted q using (part_number)
where j.est_total_cost is null
