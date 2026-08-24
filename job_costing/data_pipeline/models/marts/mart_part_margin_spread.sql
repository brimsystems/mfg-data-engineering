-- Same part, different outcomes. For repeat parts with three or more jobs in the
-- analysis year, every job with what could explain its margin against the part's
-- other jobs: the lot size against the part's median lot, the share of its
-- vertical-mill run hours on the older machines, whether it was the first run
-- after a revision, and its labor hours against estimate. The part-level spread
-- (best job less worst job, in margin points) is carried on every row.
-- Grain: job.

with s as (

    select * from {{ ref('mart_job_shortfall') }}
    where job_type = 'repeat' and release_year = {{ var('analysis_year') }}

),

parts as (

    select part_number from s group by 1 having count(*) >= 3

),

vmc as (

    select h.job_id,
           sum(case when w.install_year <= {{ var('older_machine_install_year') }} then h.run_hours else 0 end) as older_vmc_run_hours,
           sum(h.run_hours)                                                                                    as vmc_run_hours,
           string_agg(distinct h.work_center_id, ', ' order by h.work_center_id)                                as vmc_machines
    from {{ ref('int_labor_hours_by_job') }} h
    join {{ ref('stg_erp__work_centers') }} w using (work_center_id)
    where left(h.work_center_id, 3) = 'VMC'
    group by 1

),

jobs as (

    select s.job_id, s.part_number, s.part_family, s.customer_id, s.customer_name, s.material_spec, s.release_date,
           s.quantity, s.price, s.contribution, s.margin_on_price, s.coverage, s.first_after_revision, s.change_order_customer,
           s.shortfall, s.c_setup, s.c_run, s.c_material, s.c_outside, s.c_scrap_rework,
           m.labor_hours_ratio, m.setup_hours_ratio, m.run_hours_ratio, j.revision,
           v.older_vmc_run_hours, v.vmc_run_hours, v.vmc_machines,
           v.older_vmc_run_hours / nullif(v.vmc_run_hours, 0) as older_vmc_share
    from s
    join parts using (part_number)
    join {{ ref('mart_margin_by_job') }} m using (job_id)
    join {{ ref('stg_erp__jobs') }} j using (job_id)
    left join vmc v using (job_id)

)

select
    jobs.*,
    median(quantity) over (partition by part_number)                                        as part_median_lot,
    quantity / median(quantity) over (partition by part_number)                             as lot_vs_median,
    count(*) over (partition by part_number)                                                as part_jobs,
    max(margin_on_price) over (partition by part_number)
      - min(margin_on_price) over (partition by part_number)                                as part_margin_spread,
    median(margin_on_price) over (partition by part_number)                                 as part_median_margin,
    margin_on_price = min(margin_on_price) over (partition by part_number)                  as worst_job,
    margin_on_price = max(margin_on_price) over (partition by part_number)                  as best_job
from jobs
