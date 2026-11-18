/*
    BUSINESS CASES B + D: customer lifetime value, and how the FIRST payment
    relates to it. "Who are our valuable customers, and does paying in
    instalments bring them back?"

    Grain: one row per person (customer_key = customer_unique_id), same
    population as agg_customer_rfm.

    Two decisions:

    1. REALISED CLV, NOT A FORECAST. lifetime_revenue is what the customer has
       actually spent (item price, freight excluded, same caliber as every
       other revenue figure). With ~97% one-time buyers a predictive CLV model
       would be fitted on almost no repeat behaviour, so we report the
       observed value and rank it, rather than present a projection as fact.

    2. FIRST-ORDER PAYMENT. The payment type and instalment count of the
       customer's FIRST order are carried as acquisition attributes. Using the
       first order (not "ever used") keeps cause before effect: a customer who
       returns has more chances to use instalments, so "ever used" would
       inflate the apparent link between instalments and retention.
*/

{{ config(materialized='table') }}

{% set snapshot_date = var('olist_snapshot_date') %}

with orders as (

    select
        customer_key,
        order_id,
        order_purchased_at,
        order_purchase_date,
        order_revenue,
        primary_payment_type,
        max_payment_installments
    from {{ ref('fct_orders') }}
    where not is_excluded_from_kpis
        and customer_key is not null

),

first_order as (

    select
        customer_key,
        primary_payment_type     as first_payment_type,
        max_payment_installments as first_order_installments,
        order_revenue            as first_order_revenue
    from orders
    qualify row_number() over (
            partition by customer_key
            order by order_purchased_at asc, order_id asc
        ) = 1

),

lifetime as (

    select
        customer_key,
        count(*)                                                           as lifetime_orders,
        sum(order_revenue)                                                 as lifetime_revenue,
        round(avg(order_revenue), 2)                                       as avg_order_value,
        min(order_purchase_date)                                           as first_order_date,
        max(order_purchase_date)                                           as latest_order_date,
        date_diff(max(order_purchase_date), min(order_purchase_date), day) as tenure_days,
        date_diff(date('{{ snapshot_date }}'), min(order_purchase_date), day)
            as days_since_first_order,
        countif(max_payment_installments > 1)                              as orders_with_instalments
    from orders
    group by customer_key

),

combined as (

    select
        l.*,
        f.first_payment_type,
        f.first_order_installments,
        f.first_order_revenue
    from lifetime as l
    inner join first_order as f using (customer_key)

)

select
    customer_key,

    lifetime_orders,
    lifetime_revenue,
    avg_order_value,
    first_order_revenue,
    coalesce(lifetime_revenue, 0) - coalesce(first_order_revenue, 0)              as repeat_revenue,

    first_order_date,
    latest_order_date,
    tenure_days,
    days_since_first_order,

    lifetime_orders > 1                                                           as is_repeat_customer,

    coalesce(first_payment_type, 'no_payment_record')                             as first_payment_type,
    first_order_installments,
    {{ installment_band('first_order_installments') }}
        as first_installment_band,
    orders_with_instalments,

    -- 10 = top 10% of customers by realised lifetime revenue.
    ntile(10) over (order by coalesce(lifetime_revenue, 0) asc, customer_key asc)
        as clv_decile

from combined
