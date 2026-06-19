-- MES job log. Grain: one row per work order as clocked at the machine.
--
-- Two entry faults are corrected here. On about 4% of rows the start and end
-- clock entries were keyed the wrong way round; the earlier time is taken as
-- the start and the row is flagged. The badge field sometimes holds the
-- operator's name; it is resolved to the operator id through the HR roster.

with source as (

    select * from {{ source('mes', 'job_log') }}

),

roster as (

    select operator_id, operator_name from {{ source('hr', 'operators') }}

),

staged as (

    select
        s.work_order_id,
        s.machine_id,
        coalesce(r.operator_id, s.operator_badge)                               as operator_id,
        s.operator_badge                                                        as operator_badge_raw,
        least(cast(s.job_start as timestamp), cast(s.job_end as timestamp))     as job_start,
        greatest(cast(s.job_start as timestamp), cast(s.job_end as timestamp))  as job_end,
        (cast(s.job_end as timestamp) < cast(s.job_start as timestamp))         as is_clock_entry_corrected,
        cast(s.setup_minutes as double)                                         as setup_minutes,
        cast(s.run_minutes as double)                                           as run_minutes,
        s.program_or_tool_set_id
    from source s
    left join roster r
        on s.operator_badge = r.operator_name

)

select * from staged
