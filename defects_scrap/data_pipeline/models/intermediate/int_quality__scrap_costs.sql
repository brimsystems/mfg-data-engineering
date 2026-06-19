-- Scrap and rework events with the work order's dimensions.
-- Grain: one row per scrap or rework event.
--
-- Cost is the technician's estimate on the event: material and labor on
-- scrapped pieces, labor on reworked pieces.

with scrap as (

    select * from {{ ref('stg_qms__scrap_events') }}

),

orders as (

    select * from {{ ref('int_quality__orders_enriched') }}

)

select
    sc.scrap_id,
    sc.work_order_id,
    sc.inspection_id,
    sc.scrap_date,
    date_trunc('month', sc.scrap_date)  as scrap_month,
    sc.scrap_reason,
    sc.defect_code,
    sc.disposition,
    sc.quantity_scrapped,
    sc.quantity_reworked,
    sc.material_cost_per_unit,
    sc.labor_cost_per_unit,
    sc.total_scrap_cost,
    o.part_number,
    o.customer,
    o.machine_id,
    o.machine_name,
    o.machine_type,
    o.operator_id,
    o.operator_name,
    o.shift_code,
    o.complexity,
    o.material_type,
    o.supplier,
    o.lot_id,
    o.job_start
from scrap sc
inner join orders o
    on sc.work_order_id = o.work_order_id
