{#
    Buckets an instalment count into the bands used by every customer-value
    and payment model, so "how many instalments counts as long" is defined in
    exactly one place.

    0 is grouped with 1: Olist records a handful of credit-card payments with
    0 instalments, which in practice are single payments. NULL means the order
    has no payment record at all.

    Usage:  {{ installment_band('max_payment_installments') }}
#}
{% macro installment_band(column_name) -%}
    case
        when {{ column_name }} is null then '0. No payment record'
        when {{ column_name }} <= 1 then '1. Single payment'
        when {{ column_name }} <= 3 then '2. 2-3 instalments'
        when {{ column_name }} <= 6 then '3. 4-6 instalments'
        else '4. 7+ instalments'
    end
{%- endmacro %}
