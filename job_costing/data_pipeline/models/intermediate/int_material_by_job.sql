-- Material per job: as issued, and corrected where the issues sit far from the
-- part's need: a job that received another job's bar is brought back to its
-- need, a job whose bar was never issued is charged its need at the price of its
-- own issues or the month's price.

with issued as (

    select job_id, sum(value) as issued_value, sum(quantity) as issued_quantity
    from {{ ref('stg_erp__material_transactions') }}
    group by 1

),

-- the job's own issue price, in each unit of measure it was issued in (a casting can be issued by
-- the piece and its remnant by the pound), from issues only, not returns
issue_price as (

    select job_id, uom, sum(value) / nullif(sum(quantity), 0) as unit_cost
    from {{ ref('stg_erp__material_transactions') }}
    where quantity > 0
    group by 1, 2

),

need as (

    select j.job_id, j.quantity * n.need_per_piece as need_quantity, n.uom,
           m.unit_cost as month_unit_cost
    from {{ ref('stg_erp__jobs') }} j
    join {{ ref('int_part_material_need') }} n using (part_number)
    join {{ ref('stg_erp__part_master') }} p using (part_number)
    left join {{ ref('int_material_price_monthly') }} m
      on m.material_spec = p.material_spec and m.uom = n.uom and m.month = date_trunc('month', j.release_date)

),

wrong_issue as (select job_id, evidence, confidence, issued_ratio from {{ ref('dq_material_wrong_job') }})

select
    j.job_id,
    coalesce(i.issued_value, 0)                                                   as material_recorded,
    case when wrong_issue.job_id is not null then n.need_quantity * coalesce(ip.unit_cost, n.month_unit_cost)
         else coalesce(i.issued_value, 0) end                                     as material_corrected,
    case when wrong_issue.job_id is not null then 'issue, corrected to part need' else 'issue' end as material_source,
    case when wrong_issue.job_id is not null then wrong_issue.confidence else 1.0 end               as material_confidence,
    wrong_issue.evidence                                                                   as material_correction,
    i.issued_quantity,
    n.need_quantity,
    -- the part's need at the price of the day: the job's own issue price, else the month's
    n.need_quantity * coalesce(ip.unit_cost, n.month_unit_cost)                    as need_at_issue_price
from {{ ref('stg_erp__jobs') }} j
left join issued i using (job_id)
left join need n using (job_id)
left join issue_price ip on ip.job_id = j.job_id and ip.uom = n.uom
left join wrong_issue using (job_id)
