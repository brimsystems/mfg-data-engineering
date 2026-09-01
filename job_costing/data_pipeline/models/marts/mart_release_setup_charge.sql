-- Repeat-part releases against the lot the standing price was quoted at. A release
-- below half the quoted lot carries the whole setup on fewer pieces than the price
-- assumed; the setup charge is the part of the job's estimated setup the price did
-- not cover: (1 - released / quoted) x estimated setup hours x the job's pool rate.
-- The quoted lot is read from the part's quote on file: its largest quantity break
-- is four times the quoted lot. Own products and new work are excluded.
-- Grain: job (repeat releases).

with quote_on_file as (

    select part_number, quote_id, quote_date,
           row_number() over (partition by part_number order by quote_date, quote_id) as rn
    from (select distinct part_number, quote_id, quote_date from {{ ref('stg_erp__quotes') }})

),

quoted_lot as (

    select q.part_number, max(q.quantity) / 4.0 as quoted_lot
    from {{ ref('stg_erp__quotes') }} q
    join quote_on_file f on f.quote_id = q.quote_id and f.rn = 1
    group by 1

)

select
    s.job_id,
    s.part_number,
    s.part_family,
    s.customer_id,
    s.customer_name,
    s.release_date,
    s.release_year,
    s.quantity                                                                          as released_quantity,
    l.quoted_lot,
    s.quantity / l.quoted_lot                                                           as released_over_quoted,
    s.quantity < 0.5 * l.quoted_lot                                                     as below_half_quoted_lot,
    s.est_setup_hours,
    s.rate,
    s.price,
    s.contribution,
    s.margin_on_price,
    case when s.quantity < 0.5 * l.quoted_lot
         then (1 - s.quantity / l.quoted_lot) * s.est_setup_hours * s.rate else 0 end   as release_setup_charge,
    case when s.quantity < 0.5 * l.quoted_lot
         then (s.contribution + (1 - s.quantity / l.quoted_lot) * s.est_setup_hours * s.rate)
              / nullif(s.price + (1 - s.quantity / l.quoted_lot) * s.est_setup_hours * s.rate, 0)
         else s.margin_on_price end                                                     as margin_with_charge
from {{ ref('mart_job_shortfall') }} s
join quoted_lot l using (part_number)
where s.job_type = 'repeat'
