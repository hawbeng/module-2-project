/*
    BUSINESS CASE D: "Does offering instalments increase basket size?"

    Grain: one row per payment_type per instalment count.

    Built from fct_orders, where the payment has ALREADY been collapsed to one
    row per order (primary_payment_type, max_payment_installments). Joining
    fct_payments to item revenue instead would multiply revenue by the number
    of payment records per order, which is exactly the fan-out
    assert_no_payment_fanout exists to catch.

    Average order value uses order_revenue (item price, freight excluded), the
    same caliber as every other revenue figure in the project, so the numbers
    here reconcile to agg_monthly_sales.

    Read with care: this shows ASSOCIATION. Customers choose instalments
    because the basket is expensive at least as often as instalments make the
    basket bigger. The insight card should say so.
*/

{{ config(materialized='table') }}

with orders as (

    select
        coalesce(primary_payment_type, 'no_payment_record') as payment_type,
        max_payment_installments                            as installments,
        customer_key,
        order_revenue,
        order_freight,
        order_item_count,
        is_late,
        is_delivered,
        review_score
    from {{ ref('fct_orders') }}
    where not is_excluded_from_kpis

),

aggregated as (

    select
        payment_type,
        installments,
        count(*)                                                       as order_count,
        count(distinct customer_key)                                   as customers,
        sum(order_revenue)                                             as revenue,
        sum(order_freight)                                             as freight,
        round(avg(order_revenue), 2)                                   as avg_order_value,
        approx_quantiles(order_revenue, 2)[offset(1)]                  as median_order_value,
        round(avg(order_item_count), 3)                                as avg_items_per_order,
        round(safe_divide(countif(is_late), countif(is_delivered)), 4) as late_rate,
        round(avg(review_score), 3)                                    as avg_review_score
    from orders
    group by payment_type, installments

)

select
    payment_type,
    installments,
    {{ installment_band('installments') }}
        as installment_band,

    order_count,
    customers,
    revenue,
    freight,
    avg_order_value,
    median_order_value,
    avg_items_per_order,
    late_rate,
    avg_review_score,

    round(safe_divide(order_count, sum(order_count) over (partition by payment_type)), 4)
        as share_of_payment_type_orders,
    round(safe_divide(revenue, sum(revenue) over ()), 4)                                  as share_of_revenue,

    order_count >= {{ var('min_orders_for_reporting') }}
        as is_reportable

from aggregated
