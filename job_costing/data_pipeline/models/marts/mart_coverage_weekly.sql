-- Coverage through the engagement by week: traveler-scan coverage at the
-- secondary operations, and the measured share of cost on the completed jobs
-- released that week under the new process.

with scans as (

    select engagement_week, sum(operations_expected) as operations_expected, sum(operations_scanned) as operations_scanned
    from {{ ref('int_scan_coverage_weekly') }}
    group by 1

),

cost as (

    select j.engagement_week,
           count(*) as jobs_released,
           sum(f.act_total_cost) as actual_cost,
           sum(f.coverage * f.act_total_cost) as measured_cost,
           sum(f.fallback_share * f.act_total_cost) as fallback_cost,
           sum(f.unrepairable_share * f.act_total_cost) as unrepairable_cost,
           sum(f.machine_hours) as machine_hours,
           sum(f.clock_hours) as clock_hours,
           sum(f.scan_hours) as scan_hours,
           sum(f.fallback_hours) as fallback_hours
    from {{ ref('fct_job_cost') }} f
    join {{ ref('stg_erp__jobs') }} j using (job_id)
    where f.version = 'restructured' and f.status = 'completed'
    group by 1

),

weeks as (select unnest(range(1, 13)) as engagement_week)

select
    w.engagement_week,
    cast('{{ var("engagement_start") }}' as date) + to_days(cast((w.engagement_week - 1) * 7 as integer)) as week_start,
    s.operations_expected,
    s.operations_scanned,
    s.operations_scanned / nullif(s.operations_expected, 0)          as scan_coverage,
    c.jobs_released,
    c.actual_cost,
    c.measured_cost / nullif(c.actual_cost, 0)                       as measured_cost_share,
    c.fallback_cost / nullif(c.actual_cost, 0)                       as fallback_share,
    c.unrepairable_cost / nullif(c.actual_cost, 0)                   as unrepairable_share,
    c.machine_hours,
    c.clock_hours,
    c.scan_hours,
    c.fallback_hours
from weeks w
left join scans s using (engagement_week)
left join cost c using (engagement_week)
order by 1
