-- One row per error type, as the audit's findings tables present it. rows_affected
-- counts rows of the named ERP table and table_rows is that table's full row count,
-- so every share is a share of the table. scope_affected over scope_rows is the same
-- error measured in the population the test applies to (repeat parts measured,
-- records before the configuration change, and so on), where that differs.

with counts as (

    select 'jobs' as t, count(*) as n from {{ ref('stg_erp__jobs') }}
    union all select 'routings', count(*) from {{ ref('stg_erp__routings') }}
    -- the Work centers box in the audit's diagram is the rate table: the rates are what work centers provide to costing
    union all select 'work_centers', count(*) from {{ ref('stg_erp__work_center_rates') }}
    union all select 'part_master', count(*) from {{ ref('stg_erp__part_master') }}
    union all select 'quotes', count(*) from {{ ref('stg_erp__quotes') }}
    union all select 'outside_processing', count(*) from {{ ref('stg_erp__outside_processing') }}
    union all select 'labor_transactions', count(*) from {{ ref('stg_erp__labor_transactions') }}
    union all select 'scrap_rework', count(*) from {{ ref('stg_erp__scrap_rework') }}

),

register as (

    select 'stale_routing_standards' as error_code, 'Stale routing standards' as error_name, 'routings' as erp_table,
           (select count(*) from {{ ref('dq_stale_routing_standards') }}) as rows_affected,
           (select count(distinct part_number) from {{ ref('dq_stale_routing_standards') }}) as scope_affected,
           (select count(distinct part_number) from {{ ref('int_measured_cycle') }} where part_number like 'P-%') as scope_rows,
           'repeat parts with a machine-measured cycle' as scope
    union all select 'blended_shop_rate', 'One blended shop rate', 'work_centers',
           (select count(*) from {{ ref('dq_blended_shop_rate') }}),
           (select count(distinct work_center_id) from {{ ref('dq_blended_shop_rate') }}),
           (select count(*) from {{ ref('stg_erp__work_centers') }}),
           'work centers'

    union all select 'standing_price_below_target', 'Standing prices not repriced', 'part_master',
           (select count(*) from {{ ref('dq_standing_price_below_target') }}),
           (select count(*) from {{ ref('dq_standing_price_below_target') }}),
           (select count(*) from {{ ref('int_current_cost') }} where part_type = 'repeat'),
           'repeat parts'

    union all select 'stale_material_cost', 'Stale material cost in estimates', 'quotes',
           (select count(*) from {{ ref('stg_erp__quotes') }} q
             where exists (select 1 from {{ ref('dq_stale_material_cost') }} m where m.quote_id = q.quote_id and m.line = q.line)),
           (select count(*) from {{ ref('dq_stale_material_cost') }}),
           (select count(*) from {{ ref('stg_erp__quotes') }} where break_seq = 1 and quote_date >= cast('{{ var("start_date") }}' as date)),
           'quote lines in the window'

    union all select 'outside_processing_no_job', 'Outside processing not tied to jobs', 'outside_processing',
           (select count(*) from {{ ref('dq_outside_processing_no_job') }}),
           (select count(*) from {{ ref('dq_outside_processing_no_job') }} where not after_config),
           (select count(*) from {{ ref('stg_erp__outside_processing') }} where not after_config),
           'PO lines before the configuration change'

    union all select 'generic_program_numbers', 'Generic program numbers', 'routings',
           (select count(*) from {{ ref('dq_generic_program_numbers') }}),
           (select count(distinct program_number) from {{ ref('dq_generic_program_numbers') }}),
           (select count(distinct program_number) from {{ ref('stg_erp__routings') }} where program_number is not null),
           'programs'

    union all select 'own_product_standard_cost', 'Own-product standard costs never revised', 'part_master',
           (select count(*) from {{ ref('dq_own_product_standard_cost') }}),
           (select count(*) from {{ ref('dq_own_product_standard_cost') }}),
           (select count(*) from {{ ref('stg_erp__part_master') }} where own_product_flag),
           'own products'

    union all select 'open_clock_records', 'Jobs left clocked in', 'labor_transactions',
           (select count(*) from {{ ref('dq_open_clock_records') }}),
           (select count(*) from {{ ref('dq_open_clock_records') }}),
           (select count(*) from {{ ref('stg_erp__labor_transactions') }} where not after_codes and job_id is not null),
           'clock records before the labor codes'

    union all select 'setup_run_not_separated', 'Setup and run not separated', 'labor_transactions',
           (select count(*) from {{ ref('stg_erp__labor_transactions') }} where not after_codes and source = 'terminal' and job_id is not null),
           (select count(*) from {{ ref('stg_erp__labor_transactions') }} where not after_codes and source = 'terminal' and job_id is not null),
           (select count(*) from {{ ref('stg_erp__labor_transactions') }} where not after_codes and source = 'terminal' and job_id is not null),
           'terminal records before the labor codes'

    union all select 'wrong_job', 'Time charged to the wrong job', 'labor_transactions',
           (select count(*) from {{ ref('dq_wrong_job') }}),
           (select count(*) from {{ ref('dq_wrong_job') }}),
           (select count(*) from {{ ref('stg_erp__labor_transactions') }} where job_id is not null),
           'clock records with a job'

    union all select 'multi_machine_tending', 'Multi-machine tending recorded as one job', 'labor_transactions',
           (select count(*) from {{ ref('dq_multi_machine_tending') }}),
           (select count(*) from {{ ref('dq_multi_machine_tending') }}),
           (select count(*) from {{ ref('stg_erp__labor_transactions') }}
             where not after_codes and job_id is not null and left(work_center_id, 3) in ('VMC', 'FAX', 'HMC', 'LTH', 'MTN', 'SWS', 'EDM')),
           'clock records on monitored cells before the labor codes'

    union all select 'indirect_time_on_jobs', 'Indirect time charged to jobs', 'labor_transactions',
           (select count(*) from {{ ref('dq_indirect_time_on_jobs') }}),
           (select count(*) from {{ ref('dq_indirect_time_on_jobs') }}),
           (select count(*) from {{ ref('stg_erp__labor_transactions') }} where not after_codes and job_id is not null),
           'clock records before the labor codes'

    -- every rework event before the rework code posted as run time: on the catch-all
    -- operation, where it can be seen, or inside the operation's own run time
    union all select 'rework_as_run', 'Rework recorded as run time', 'scrap_rework',
           (select count(*) from {{ ref('dq_rework_as_run') }}),
           (select count(*) from {{ ref('dq_rework_as_run') }} where hours_on_999 is null),
           (select count(*) from {{ ref('dq_rework_as_run') }}),
           'inside the operation''s run time'

    union all select 'scrap_unrecorded', 'Scrap without reason or without job', 'scrap_rework',
           (select count(*) from {{ ref('dq_scrap_unrecorded') }} where detection = 'recorded event'),
           (select count(*) from {{ ref('dq_scrap_unrecorded') }} where detection = 'recorded event'),
           (select count(*) from {{ ref('stg_erp__scrap_rework') }} where not after_config),
           'events before the reason code was required'

    union all select 'material_wrong_job', 'Material issued to the wrong job or not issued', 'jobs',
           (select count(*) from {{ ref('dq_material_wrong_job') }}),
           (select count(*) from {{ ref('dq_material_wrong_job') }}),
           (select count(*) from {{ ref('stg_erp__jobs') }}),
           'jobs'

    union all select 'missing_scans', 'Missing scans during rollout', 'jobs',
           (select count(distinct job_id) from {{ ref('dq_missing_scans') }}),
           (select count(*) from {{ ref('dq_missing_scans') }}),
           (select sum(operations_expected) from {{ ref('int_scan_coverage_weekly') }}),
           'secondary operations after the rollout began'

    union all select 'labor_posting_off', 'Labor posting never turned on at three secondary cells', 'jobs',
           (select count(distinct job_id) from {{ ref('dq_labor_posting_off') }}),
           (select count(distinct job_id) from {{ ref('dq_labor_posting_off') }}),
           (select count(*) from {{ ref('stg_erp__jobs') }} where release_date < cast('{{ var("scan_rollout_date") }}' as date)),
           'jobs released before the rollout'

)

select
    r.error_code,
    r.error_name,
    r.erp_table,
    r.rows_affected,
    c.n                                              as table_rows,
    r.rows_affected / c.n                            as share_of_table,
    r.scope_affected,
    r.scope_rows,
    r.scope_affected / nullif(r.scope_rows, 0)       as share_of_scope,
    r.scope,
    -- the scope line is shown only where it measures something other than the table
    not (r.scope_affected = r.rows_affected and r.scope_rows = c.n) as show_scope
from register r
join counts c on c.t = r.erp_table
