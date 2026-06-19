-- QMS scrap and rework events. Grain: one row per event.
--
-- The reason is taken from the structured code; the text as entered is kept
-- beside it. Cost fields are the technician's estimate.

select
    scrap_id,
    work_order_id,
    inspection_id,
    cast(scrap_date as timestamp)               as scrap_date,
    defect_code_clean                           as defect_code,
    disposition,
    cast(quantity_scrapped as integer)          as quantity_scrapped,
    cast(quantity_reworked as integer)          as quantity_reworked,
    scrap_reason_clean                          as scrap_reason,
    scrap_reason_raw,
    cast(material_cost_per_unit as double)      as material_cost_per_unit,
    cast(labor_cost_per_unit as double)         as labor_cost_per_unit,
    cast(total_scrap_cost as double)            as total_scrap_cost
from {{ source('qms', 'scrap_events') }}
