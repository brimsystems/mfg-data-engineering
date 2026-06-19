-- Operator summary. Grain: one row per operator and machine type.
--
-- Experience is the operator's jobs on the machine type at the end of the
-- record (estimated prior jobs plus the job-log count).

with orders as (

    select * from {{ ref('mart_quality__defect_rates') }}

)

select
    operator_id,
    operator_name,
    hire_date,
    cert_level,
    assigned_shift,
    primary_machine_type,
    machine_type,
    (machine_type <> primary_machine_type)                              as is_coverage,
    is_hired_in_period,
    count(*)                                                            as jobs,
    sum(quantity_inspected)                                             as quantity_inspected,
    sum(quantity_failed)                                                as quantity_failed,
    round(sum(quantity_failed)::double / nullif(sum(quantity_inspected), 0), 4)  as defect_rate,
    round(max(jobs_on_machine_type_before) + 1, 0)                      as jobs_on_machine_type,
    round(sum(scrap_cost), 2)                                           as scrap_cost,
    max(production_day)                                                 as last_production_day
from orders
group by all
