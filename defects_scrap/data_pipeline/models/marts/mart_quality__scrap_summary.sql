-- Scrap and rework events with their cost. Grain: one row per event.

select
    scrap_id,
    work_order_id,
    inspection_id,
    scrap_date,
    scrap_month,
    part_number,
    customer,
    machine_id,
    machine_name,
    machine_type,
    operator_id,
    operator_name,
    shift_code,
    complexity,
    material_type,
    supplier,
    lot_id,
    scrap_reason,
    defect_code,
    disposition,
    quantity_scrapped,
    quantity_reworked,
    material_cost_per_unit,
    labor_cost_per_unit,
    total_scrap_cost
from {{ ref('int_quality__scrap_costs') }}
