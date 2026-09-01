-- The same replay at 10%, 15% and 20%, for the choice of threshold: by release year
-- and threshold, the completed jobs, how many the flag fired on, how many while
-- the job was still open, how many of the flagged jobs recovered by close, and the
-- overrun after the flag. Grain: release year, threshold.

select
    release_year,
    threshold,
    count(*)                                                              as jobs,
    sum(case when flagged then 1 else 0 end)                              as flagged,
    sum(case when flagged_with_operations_left then 1 else 0 end)         as flagged_with_operations_left,
    sum(case when flagged_while_open then 1 else 0 end)                   as flagged_while_open,
    sum(case when flagged and recovered_by_close then 1 else 0 end)       as recovered_by_close,
    sum(case when flagged then overrun else 0 end)                        as overrun_on_flagged_jobs,
    coalesce(sum(overrun_after_flag), 0)                                  as overrun_after_flag,
    sum(overrun)                                                          as net_overrun
from {{ ref('int_inprogress_flag') }}
group by 1, 2
