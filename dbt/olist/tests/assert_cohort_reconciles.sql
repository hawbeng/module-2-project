/*
    Proves the retention table neither lost nor double-counted anyone.

    Severity: error. A retention curve is the headline chart of business
    case B, and a cohort grid that drops or duplicates customers produces a
    curve that is wrong yet entirely plausible.

    1. Every cohort's month-0 row has active_customers == cohort_size, i.e.
       retention_rate == 1. Anything else means the first-month logic and the
       activity logic disagree about who joined when.

    2. Cohort sizes sum to the number of people in agg_customer_rfm. Same
       population, same exclusions; a mismatch means a different filter crept
       in, or the cohort was keyed on the per-order customer_id.

    3. Orders and revenue summed across the whole grid equal fct_orders (kept
       orders only). The dense grid adds zero rows; this proves it added
       nothing else.
*/

with month_zero as (

    select
        countif(active_customers != cohort_size) as bad_month_zero_rows,
        sum(cohort_size)                         as cohort_people
    from {{ ref('agg_customer_cohort') }}
    where months_since_first = 0

),

grid_totals as (

    select
        sum(order_count) as grid_orders,
        sum(revenue)     as grid_revenue
    from {{ ref('agg_customer_cohort') }}

),

rfm as (

    select count(*) as rfm_people
    from {{ ref('agg_customer_rfm') }}

),

fact as (

    select
        count(*)           as fact_orders,
        sum(order_revenue) as fact_revenue
    from {{ ref('fct_orders') }}
    where not is_excluded_from_kpis
        and customer_key is not null

),

checks as (

    select
        m.bad_month_zero_rows,
        m.cohort_people,
        r.rfm_people,
        g.grid_orders,
        f.fact_orders,
        g.grid_revenue,
        f.fact_revenue
    from month_zero as m
    cross join grid_totals as g
    cross join rfm as r
    cross join fact as f

)

select
    *,
    case
        when bad_month_zero_rows > 0
            then 'month-0 retention is not 1.0 for some cohort'
        when cohort_people != rfm_people
            then 'cohort sizes do not sum to the agg_customer_rfm population'
        when grid_orders != fact_orders
            then 'cohort order count does not reconcile to fct_orders'
        else 'cohort revenue does not reconcile to fct_orders'
    end as violation
from checks
where bad_month_zero_rows > 0
    or cohort_people != rfm_people
    or grid_orders != fact_orders
    or grid_revenue is distinct from fact_revenue
