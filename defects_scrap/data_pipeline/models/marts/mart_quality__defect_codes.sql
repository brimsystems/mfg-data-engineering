-- Failed pieces by defect code. Grain: one row per month, machine type and code.
--
-- A final inspection carries one defect code for the job; the job's failed
-- pieces are counted under it.

select
    production_month,
    machine_type,
    defect_code,
    count(*)                    as jobs_with_code,
    sum(quantity_failed)        as quantity_failed,
    round(sum(scrap_cost), 2)   as scrap_cost
from {{ ref('mart_quality__defect_rates') }}
where quantity_failed > 0
group by 1, 2, 3
