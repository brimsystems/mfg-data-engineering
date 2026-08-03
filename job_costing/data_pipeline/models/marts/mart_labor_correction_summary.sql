-- The labor cleanup by work center: records by rule and status, hours, and the
-- unrepairable share.

select
    work_center_id,
    left(work_center_id, 3)                                          as work_center_group,
    monitored_flag,
    rule,
    status,
    count(*)                                                         as records,
    sum(hours)                                                       as hours_recorded,
    sum(case when status = 'removed' then 0 else corrected_hours end) as hours_corrected,
    avg(confidence)                                                  as mean_confidence
from {{ ref('int_labor_cleaned') }}
where not after_codes
group by 1, 2, 3, 4, 5
