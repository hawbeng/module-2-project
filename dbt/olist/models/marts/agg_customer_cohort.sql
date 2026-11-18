/*
    BUSINESS CASE B: customer retention. "Why do so few customers come back?"

    Grain: one row per acquisition cohort (month of the customer's first kept
    order) per months_since_first (0, 1, 2, ...).

    Three decisions:

    1. PERSON GRAIN. Cohorts are built on customer_key (customer_unique_id),
       never on the per-order customer_id. On customer_id every cohort would
       show 0% retention after month 0, because Olist issues a fresh id for
       every order.

    2. DENSE GRID. Every cohort gets a row for every month from its first
       month up to the last month in the data, even when nobody returned. A
       sparse table would silently drop the zero-retention months, and a
       retention curve drawn from it would look better than reality.

    3. SAME EXCLUSIONS AS EVERYWHERE ELSE. Only orders that survive the
       excluded_order_statuses var count, so cohort sizes equal the row count
       of agg_customer_rfm and revenue reconciles to fct_orders.

    retention_rate in month 0 is 1.0 by construction; a test asserts it.
*/

{{ config(materialized='table') }}

with orders as (

    select
        customer_key,
        date_trunc(order_purchase_date, month) as order_month,
        order_revenue
    from {{ ref('fct_orders') }}
    where not is_excluded_from_kpis
        and customer_key is not null

),

first_month as (

    select
        customer_key,
        min(order_month) as cohort_month
    from orders
    group by customer_key

),

activity as (

    select
        f.cohort_month,
        date_diff(o.order_month, f.cohort_month, month) as months_since_first,
        count(distinct o.customer_key)                  as active_customers,
        count(*)                                        as order_count,
        sum(o.order_revenue)                            as revenue
    from orders as o
    inner join first_month as f using (customer_key)
    group by f.cohort_month, months_since_first

),

cohort_size as (

    select
        cohort_month,
        count(*) as cohort_size
    from first_month
    group by cohort_month

),

last_month as (

    select max(order_month) as last_order_month
    from orders

),

grid as (

    select
        c.cohort_month,
        c.cohort_size,
        months_since_first
    from cohort_size as c
    cross join last_month as l
    cross join
        unnest(
            generate_array(0, date_diff(l.last_order_month, c.cohort_month, month))
        ) as months_since_first

)

select
    g.cohort_month,
    format_date('%Y-%m', g.cohort_month)                                  as cohort_year_month,
    g.months_since_first,
    date_add(g.cohort_month, interval g.months_since_first month)         as activity_month,
    g.cohort_size,

    coalesce(a.active_customers, 0)                                       as active_customers,
    coalesce(a.order_count, 0)                                            as order_count,
    coalesce(a.revenue, 0)                                                as revenue,

    round(safe_divide(coalesce(a.active_customers, 0), g.cohort_size), 4) as retention_rate,
    g.cohort_month between date('{{ var("analysis_start_date") }}')
    and date('{{ var("analysis_end_date") }}')                                                      as is_in_analysis_window

from grid as g
left join activity as a
    on
        g.cohort_month = a.cohort_month
        and g.months_since_first = a.months_since_first
