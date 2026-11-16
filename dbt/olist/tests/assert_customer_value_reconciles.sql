/*
    Proves the two new customer-value models agree with the models they sit
    beside, to the cent.

    Severity: error.

    agg_customer_clv vs agg_customer_rfm (same people, same caliber):
      1. Same number of rows.
      2. Per person, lifetime_orders == frequency and lifetime_revenue ==
         monetary. Checked row by row, so two errors cannot cancel out in a
         total.

    agg_installment_basket vs fct_orders (kept orders):
      3. Order count and revenue both reconcile exactly. If anyone rebuilds
         the basket from fct_payments joined to items, revenue multiplies by
         the number of payment records and this fails.
*/

with clv_vs_rfm as (

    select
        countif(c.customer_key is null)                         as missing_in_clv,
        countif(r.customer_key is null)                         as missing_in_rfm,
        countif(c.lifetime_orders != r.frequency)               as order_mismatches,
        countif(c.lifetime_revenue is distinct from r.monetary) as revenue_mismatches
    from {{ ref('agg_customer_clv') }} as c
    full outer join {{ ref('agg_customer_rfm') }} as r using (customer_key)

),

basket as (

    select
        sum(order_count) as basket_orders,
        sum(revenue)     as basket_revenue
    from {{ ref('agg_installment_basket') }}

),

fact as (

    select
        count(*)           as fact_orders,
        sum(order_revenue) as fact_revenue
    from {{ ref('fct_orders') }}
    where not is_excluded_from_kpis

),

checks as (

    select
        cr.missing_in_clv,
        cr.missing_in_rfm,
        cr.order_mismatches,
        cr.revenue_mismatches,
        b.basket_orders,
        f.fact_orders,
        b.basket_revenue,
        f.fact_revenue
    from clv_vs_rfm as cr
    cross join basket as b
    cross join fact as f

)

select *
from checks
where missing_in_clv > 0
    or missing_in_rfm > 0
    or order_mismatches > 0
    or revenue_mismatches > 0
    or basket_orders != fact_orders
    or basket_revenue is distinct from fact_revenue
