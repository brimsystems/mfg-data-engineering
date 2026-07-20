with source as (

    select * from {{ source('machinemetrics', 'machines') }}

),

staged as (

    select
        machine_id,
        machine_type,
        controller_type,
        location_cell,
        cast(machine_age_years as integer)  as machine_age_years,
        cast(max_spindle_rpm as integer)    as max_spindle_rpm,
        cast(install_date as date)          as install_date,

        -- Days since the last repair at which the shop services the machine.
        cast(repair_interval_days as integer) as repair_interval_days

    from source

)

select * from staged
