-- One row per error type: the table it lives in, rows affected, rows in scope
-- and the share, as the audit's findings tables present them.

{% set rows = [
    ("M1", "Estimate not attached to the job", "jobs", "dq_m1_estimate_not_on_job", "", "count(*)", "stg_erp__jobs", "where not released_after_config", "count(*)", "jobs before the configuration change"),
    ("M2", "Stale routing standards", "routings", "dq_m2_stale_routing_standards", "", "count(distinct part_number)", "int_measured_cycle", "where part_number like 'P-%'", "count(distinct part_number)", "repeat parts with a measured cycle"),
    ("M3", "One blended shop rate", "work_center_rates", "dq_m3_blended_shop_rate", "", "count(distinct work_center_id)", "stg_erp__work_centers", "", "count(*)", "work centers"),
    ("M4", "Standing prices not repriced", "part_master", "dq_m4_standing_price_below_target", "", "count(*)", "int_current_cost", "where part_type = 'repeat'", "count(*)", "repeat parts"),
    ("M5", "Stale material cost in estimates", "quotes", "dq_m5_stale_material_cost", "", "count(*)", "stg_erp__quotes", "where break_seq = 1 and quote_date >= cast('" ~ var('start_date') ~ "' as date)", "count(*)", "quote lines in the window"),
    ("M6", "Outside processing not tied to jobs", "outside_processing", "dq_m6_outside_processing_no_job", "where not after_config", "count(*)", "stg_erp__outside_processing", "where not after_config", "count(*)", "PO lines before the configuration change"),
    ("M7", "Generic program numbers", "routings", "dq_m7_generic_program_numbers", "", "count(distinct program_number)", "stg_erp__routings", "where program_number is not null", "count(distinct program_number)", "programs"),
    ("M8", "Own-product standard costs never revised", "part_master", "dq_m8_own_product_standard_cost", "", "count(*)", "stg_erp__part_master", "where own_product_flag", "count(*)", "own products on the part master"),
    ("T1", "Jobs left clocked in", "labor_transactions", "dq_t1_open_clock_records", "", "count(*)", "stg_erp__labor_transactions", "where not after_codes and job_id is not null", "count(*)", "clock records before the labor codes"),
    ("T2", "Setup and run not separated", "labor_transactions", "stg_erp__labor_transactions", "where not after_codes and source = 'terminal' and job_id is not null", "count(*)", "stg_erp__labor_transactions", "where not after_codes and source = 'terminal' and job_id is not null", "count(*)", "clock records before the labor codes"),
    ("T3", "Time charged to the wrong job", "labor_transactions", "dq_t3_wrong_job", "", "count(*)", "stg_erp__labor_transactions", "where job_id is not null", "count(*)", "clock records"),
    ("T4", "Multi-machine tending recorded as one job", "labor_transactions", "dq_t4_multi_machine_tending", "", "count(*)", "stg_erp__labor_transactions", "where not after_codes and job_id is not null and left(work_center_id, 3) in ('VMC', 'FAX', 'HMC', 'LTH', 'MTN', 'SWS', 'EDM')", "count(*)", "clock records on monitored cells before the labor codes"),
    ("T5", "Indirect time charged to jobs", "labor_transactions", "dq_t5_indirect_time_on_jobs", "", "count(*)", "stg_erp__labor_transactions", "where not after_codes and job_id is not null", "count(*)", "clock records before the labor codes"),
    ("T6", "Rework recorded as run time", "scrap_rework", "dq_t6_rework_as_run", "where hours_on_999 is null", "count(*)", "dq_t6_rework_as_run", "", "count(*)", "rework events before the rework code"),
    ("T7", "Scrap without reason or without job", "scrap_rework", "dq_t7_scrap_unrecorded", "where detection = 'recorded event'", "count(*)", "stg_erp__scrap_rework", "where not after_config", "count(*)", "scrap and rework events before the reason code was required"),
    ("T8", "Material issued to the wrong job or not issued", "material_transactions", "dq_t8_material_wrong_job", "", "count(*)", "stg_erp__jobs", "", "count(*)", "jobs"),
    ("T9", "Missing scans during rollout", "labor_transactions", "dq_t9_missing_scans", "", "count(*)", "int_scan_coverage_weekly", "", "sum(operations_expected)", "secondary operations after the rollout began"),
    ("T10", "Labor posting never turned on at three secondary cells", "labor_transactions", "dq_t10_labor_posting_off", "", "count(distinct job_id)", "stg_erp__jobs", "where release_date < cast('" ~ var('scan_rollout_date') ~ "' as date)", "count(*)", "jobs released before the rollout"),
] %}

{% for code, name, table, a_model, a_filter, a_expr, s_model, s_filter, s_expr, scope_label in rows %}
select
    '{{ code }}'                                    as error_code,
    '{{ name }}'                                    as error_name,
    '{{ table }}'                                   as erp_table,
    (select {{ a_expr }} from {{ ref(a_model) }} {{ a_filter }}) as rows_affected,
    (select {{ s_expr }} from {{ ref(s_model) }} {{ s_filter }}) as rows_in_scope,
    '{{ scope_label }}'                             as scope
{% if not loop.last %}union all{% endif %}
{% endfor %}
