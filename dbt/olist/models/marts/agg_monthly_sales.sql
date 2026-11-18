/*
    BRIEF REQUIREMENT: monthly sales trends.

    Grain: one row per purchase month.

    Definitions, fixed here so no chart can quietly use a different one:
      revenue      = sum of item price. Freight is a SEPARATE column and is
                     never folded into revenue, because freight is a cost the
                     customer bears, not merchandise value.
      order_count  = count of distinct orders, taken from fct_orders where the
                     grain is already one row per order.
      exclusions   = the statuses in the excluded_order_statuses project var.

    Revenue comes from fct_order_items and order counts from fct_orders, each at
    its own natural grain and joined only after aggregation. Computing both from
    one joined query is exactly the mistake that inflates revenue by the item
    count, so the two are kept apart until they are both scalars per month.

    B + D scope: alongside revenue, each month carries how much of it came from
    NEW versus RETURNING people (case B, "spend over time") and how much of it
    was paid in instalments (case D). Late rate and review score are computed
    directly from fct_orders, with the same caliber as agg_customer_rfm, so the
    service-quality cross-read survives without the delivery marts.
*/

{{ config(materialized='table') }}

with items as (

    select *
    from {{ ref('fct_order_items') }}
    where not is_excluded_from_kpis

),

item_revenue as (

    select
        date_trunc(order_purchase_date, month) as month_start_date,
        sum(item_price)                        as revenue,
        sum(freight_value)                     as freight,
        sum(item_gross_value)                  as gross_value,
        count(*)                               as items_sold,
        count(distinct product_key)            as distinct_products_sold,
        count(distinct seller_key)             as active_sellers
    from items
    group by month_start_date

),

orders as (

    select
        customer_key,
        order_id,
        order_purchased_at,
        date_trunc(order_purchase_date, month) as month_start_date,
        order_revenue,
        max_payment_installments,
        is_delivered,
        is_late,
        total_delivery_days,
        review_score
    from {{ ref('fct_orders') }}
    where not is_excluded_from_kpis

),

-- A person's first kept order makes them "new" in that month; every later
-- order is "returning". Person grain (customer_key), never customer_id.
order_sequence as (

    select
        *,
        row_number() over (
            partition by customer_key
            order by order_purchased_at asc, order_id asc
        ) = 1 as is_first_order
    from orders

),

order_counts as (

    select
        month_start_date,
        count(*)                                                       as order_count,
        count(distinct customer_key)                                   as active_customers,

        -- ---------------- case B: new vs returning ----------------
        countif(is_first_order)                                        as new_customers,
        count(distinct if(not is_first_order, customer_key, null))     as returning_customers,
        sum(if(is_first_order, order_revenue, 0))                      as new_customer_revenue,
        sum(if(not is_first_order, order_revenue, 0))                  as returning_customer_revenue,

        -- ---------------- case D: instalments ----------------
        countif(max_payment_installments > 1)                          as instalment_orders,
        sum(if(max_payment_installments > 1, order_revenue, 0))        as instalment_revenue,
        round(avg(max_payment_installments), 3)                        as avg_installments,

        -- ---------------- service quality cross-read ----------------
        round(safe_divide(countif(is_late), countif(is_delivered)), 4) as late_rate,
        approx_quantiles(total_delivery_days, 2)[offset(1)]            as median_delivery_days,
        round(avg(review_score), 3)                                    as avg_review_score
    from order_sequence
    group by month_start_date

),

calendar as (

    select distinct
        month_start_date,
        year_month,
        month_label,
        is_in_analysis_window
    from {{ ref('dim_date') }}

),

combined as (

    select
        c.year_month,
        c.month_label,
        c.month_start_date,
        c.is_in_analysis_window,

        r.revenue,
        r.freight,
        r.gross_value,
        r.items_sold,
        r.distinct_products_sold,
        r.active_sellers,

        o.order_count,
        o.active_customers,
        o.new_customers,
        o.returning_customers,
        o.new_customer_revenue,
        o.returning_customer_revenue,
        o.instalment_orders,
        o.instalment_revenue,
        o.avg_installments,

        o.late_rate,
        o.median_delivery_days,
        o.avg_review_score

    from calendar as c
    inner join item_revenue as r using (month_start_date)
    left join order_counts as o using (month_start_date)

)

select
    *,

    round(safe_divide(revenue, order_count), 2)                                       as avg_order_value,
    round(safe_divide(items_sold, order_count), 3)                                    as avg_items_per_order,
    round(safe_divide(freight, gross_value), 4)                                       as freight_share_of_gross,
    round(safe_divide(returning_customer_revenue, revenue), 4)                        as returning_revenue_share,
    round(safe_divide(instalment_orders, order_count), 4)                             as instalment_order_share,
    round(safe_divide(instalment_revenue, revenue), 4)                                as instalment_revenue_share,

    round(safe_divide(revenue, lag(revenue) over (order by month_start_date)) - 1, 4)
        as revenue_mom_growth

from combined
order by month_start_date
