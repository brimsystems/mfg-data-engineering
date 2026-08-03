-- Fill rates of the fields the audit depends on, per table, before and after the
-- configuration changes. Grain: one row per table, field and period.

{% set checks = [
    ('jobs', 'est_total_cost', 'stg_erp__jobs', 'released_after_config'),
    ('jobs', 'completed_date', 'stg_erp__jobs', 'released_after_config'),
    ('outside_processing', 'job_id', 'stg_erp__outside_processing', 'after_config'),
    ('outside_processing', 'description_part_number', 'stg_erp__outside_processing', 'after_config'),
    ('scrap_rework', 'reason_code', 'stg_erp__scrap_rework', 'after_config'),
    ('scrap_rework', 'job_id', 'stg_erp__scrap_rework', 'after_config'),
    ('machine_monitoring', 'assigned_job_id', 'stg_monitoring__machine_monitoring', "start_time >= cast('" ~ var('monitoring_to_jobs_date') ~ "' as timestamp)"),
    ('labor_transactions', 'job_id', 'stg_erp__labor_transactions', 'after_codes'),
] %}

{% for table, field, model, period in checks %}
select
    '{{ table }}' as erp_table,
    '{{ field }}' as field,
    case when {{ period }} then 'after configuration change' else 'before' end as period,
    count(*) as rows_in_scope,
    count({{ field }}) as rows_filled,
    round(count({{ field }}) / count(*), 4) as fill_rate
from {{ ref(model) }}
group by 1, 2, 3
{% if not loop.last %}union all{% endif %}
{% endfor %}
