"""Olist Customer Value & Instalments — interactive dashboard (cases B + D).

Answers the project's two business questions for someone who will not open a
notebook:

    B. Who are our valuable customers, and why do so few come back?
    D. Does offering instalments increase basket size?

Two rules this app follows, both of which come from the project's architecture
rather than from Streamlit convention:

1. IT READS THE MARTS LAYER ONLY. No CSV, no raw tables, no local files. Every
   number shown here comes from a dbt model that has tests attached to it. If a
   figure is wrong, it is wrong in a tested model and it is wrong identically in
   the notebooks and the report -- rather than being a fourth, untested version
   of the truth.

2. IT DOES NOT REDEFINE METRICS. The definitions live in dbt. Where interactive
   filtering forces a figure to be recomputed against fct_orders (because a
   pre-aggregated model cannot be sliced by an arbitrary filter combination),
   the predicate is confined to KEPT_ORDERS_SQL below and the Data quality tab
   checks the unfiltered recomputation still agrees with agg_monthly_sales.

Run:
    make dashboard
    # or: streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Olist Customer Value",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# warehouse.py sits at the repository root precisely so this app and the
# notebooks resolve datasets the same way. It raises on import when the project
# is not configured, so the import is guarded: an unconfigured checkout should
# get setup instructions, not a stack trace.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from warehouse import PROJECT_ID, SNAPSHOT_DATE, marts, q, staging  # noqa: E402
except RuntimeError as exc:
    st.title("📦 Olist Customer Value")
    st.error(f"**Not configured yet.** {exc}")
    st.markdown(
        """
Before this dashboard can run:

1. `cp .env.example .env` and fill in `GCP_PROJECT_ID`, `GCS_RAW_BUCKET` and
   `DBT_DEV_DATASET`
2. `gcloud auth application-default login`
3. `make all` — so the marts layer exists to read from

Full instructions: `README.md`, or run `notebooks/00_runbook.ipynb`.
"""
    )
    st.stop()

NAVY, ACCENT, GOOD, BAD, MUTED = "#1f3864", "#c55a11", "#2e7d32", "#c62828", "#8a8a8a"
REGION_ORDER = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]


# The one place in this app where the order population is expressed in SQL.
# Mirrors the dbt var excluded_order_statuses: canceled and unavailable orders
# are not purchases for customer-value or payment purposes.
KEPT_ORDERS_SQL = "not is_excluded_from_kpis"


# --------------------------------------------------------------------------- #
# Data access
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=900, show_spinner="Querying BigQuery…")
def run(sql: str) -> pd.DataFrame:
    """Cached query. BigQuery charges by bytes scanned, so repeated interaction
    with the same filters costs nothing after the first call."""
    return q(sql)



@st.cache_data(ttl=900)
def load_filter_options() -> tuple[list[str], list[str]]:
    df = run(f"""
        select year_month
        from {marts('agg_monthly_sales')}
        where is_in_analysis_window
        order by year_month
    """)
    regions = run(f"""
        select distinct customer_region
        from {marts('dim_customer')}
        where customer_region is not null
        order by customer_region
    """)
    return df.year_month.tolist(), regions.customer_region.tolist()


def where_clause(months: tuple[str, str], regions: list[str], all_regions: list[str]) -> str:
    """Build the shared filter predicate applied to every fct_orders query."""
    clauses = [
        KEPT_ORDERS_SQL,
        f"format_date('%Y-%m', order_purchase_date) between '{months[0]}' and '{months[1]}'",
    ]
    if regions and set(regions) != set(all_regions):
        quoted = ", ".join(f"'{r}'" for r in regions)
        clauses.append(f"customer_region in ({quoted})")
    return " and ".join(f"({c})" for c in clauses)



def pct(value, digits=1):
    return "—" if pd.isna(value) else f"{value:.{digits}%}"


def count(value):
    """Format an integer measure.

    DataFrame.iloc[0] upcasts an all-numeric row to float64, so counts arrive
    here as floats and a bare ",` format would render "92,345.0".
    """
    return "—" if pd.isna(value) else f"{value:,.0f}"


def money(value):
    return "—" if pd.isna(value) else f"R$ {value:,.0f}"


def money_compact(value):
    """Short money for KPI tiles, which are too narrow for a full figure."""
    if pd.isna(value):
        return "—"
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= limit:
            return f"R$ {value / limit:,.2f}{suffix}"
    return f"R$ {value:,.0f}"


# st.column_config.NumberColumn does NOT multiply a fraction by 100 for a "%"
# format string -- 0.25 renders as "0.2%". Scale explicitly for table display
# while leaving the underlying fraction untouched for the charts.
def as_percent(df: pd.DataFrame, *columns: str) -> pd.DataFrame:
    out = df.copy()
    for column in columns:
        if column in out:
            out[column] = out[column] * 100
    return out


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
st.sidebar.title("📦 Olist Customers")
st.sidebar.caption(f"`{PROJECT_ID}` · marts layer · snapshot {SNAPSHOT_DATE}")

try:
    months, all_regions = load_filter_options()
except Exception as exc:  # noqa: BLE001
    st.error(
        "Could not reach the marts layer.\n\n"
        "Check that `.env` is filled in, that `gcloud auth application-default "
        "login` has been run, and that `make build` has completed at least once."
    )
    st.exception(exc)
    st.stop()

if not months:
    st.error("`agg_monthly_sales` is empty. Run `make build` first.")
    st.stop()

st.sidebar.subheader("Filters")
month_range = st.sidebar.select_slider(
    "Purchase month",
    options=months,
    value=(months[0], months[-1]),
    help=(
        "Orders are bucketed by PURCHASE month. Only months inside the usable "
        "coverage window are offered — the sparse first and last months of the "
        "export are excluded so they cannot be read as a demand collapse."
    ),
)
selected_regions = st.sidebar.multiselect(
    "Customer region", all_regions, default=all_regions,
    help="Filters on the customer's IBGE macro-region (headline tiles and the spend-over-time tab).",
)
min_orders = st.sidebar.number_input(
    "Minimum cohort / segment size", min_value=1, max_value=500, value=30, step=10,
    help="Small groups are noise. Cohorts below this size are hidden from the heatmap.",
)

if not selected_regions:
    st.sidebar.warning("Select at least one region.")
    st.stop()

WHERE = where_clause(month_range, selected_regions, all_regions)
CUSTOMER_WHERE = WHERE


st.sidebar.divider()
st.sidebar.caption(
    "Every figure comes from a tested dbt model in the marts layer. "
    "Definitions: `dbt/olist/models/marts/_olist__marts.yml`."
)


# --------------------------------------------------------------------------- #
# Header + headline KPIs
# --------------------------------------------------------------------------- #
st.title("Who are our valuable customers, and what brings them back?")
st.caption(
    f"Kept orders purchased between **{month_range[0]}** and **{month_range[1]}** · "
    f"{len(selected_regions)} of {len(all_regions)} regions · "
    "canceled and unavailable orders excluded · customers counted as people "
    "(`customer_unique_id`)"
)


customer_head = run(f"""
    with per_person as (
        select
            customer_key,
            count(*)           as orders,
            sum(order_revenue) as revenue
        from {marts('fct_orders')}
        where {CUSTOMER_WHERE}
        group by customer_key
    )
    select
        (select count(*) from per_person)                               as customers,
        (select countif(orders > 1) from per_person)                    as repeat_customers,
        (select sum(revenue) from per_person)                           as revenue,
        (select sum(orders) from per_person)                            as orders,
        (select countif(primary_payment_type = 'credit_card')
           from {marts('fct_orders')} where {CUSTOMER_WHERE})           as card_orders,
        (select countif(primary_payment_type = 'credit_card'
                        and max_payment_installments > 1)
           from {marts('fct_orders')} where {CUSTOMER_WHERE})           as instalment_orders
""").iloc[0]

if not customer_head.customers:
    st.warning("No orders match these filters.")
    st.stop()

tiles = [
    ("Customers", count(customer_head.customers),
     "people with a kept order in the filter"),
    ("Repeat-purchase rate", pct(customer_head.repeat_customers / customer_head.customers, 2),
     f"{count(customer_head.repeat_customers)} bought more than once"),
    ("Revenue per customer", money(customer_head.revenue / customer_head.customers),
     f"{money_compact(customer_head.revenue)} in total"),
    ("Average order value", money(customer_head.revenue / customer_head.orders),
     f"{count(customer_head.orders)} orders"),
    ("Card orders in instalments",
     pct(customer_head.instalment_orders / max(customer_head.card_orders, 1)),
     f"{count(customer_head.instalment_orders)} of {count(customer_head.card_orders)}"),
]
for column, (label, value, note) in zip(st.columns(5), tiles):
    column.metric(label, value)
    column.caption(note)

st.divider()

(tab_customers, tab_segments, tab_spend, tab_instalments, tab_quality) = st.tabs(
    ["👥 Customer value", "🎯 RFM segments", "📈 Spend over time",
     "💳 Instalments", "✅ Data quality"]
)


# --------------------------------------------------------------------------- #
# CUSTOMER VALUE & RETENTION  (business case B)
# --------------------------------------------------------------------------- #
with tab_customers:
    st.subheader("Who are our valuable customers, and why do so few come back?")
    st.caption(
        "Person grain (`customer_unique_id`), kept orders only. Lifetime value is "
        "**realised** spend (item price, freight excluded), not a forecast: with almost "
        "every customer buying once, a predictive model would have nothing to learn from. "
        "Reads `agg_customer_clv` and `agg_customer_cohort`; the region filter does not apply, "
        "the month filter selects acquisition cohorts."
    )

    clv_head = run(f"""
        select
            count(*)                                                       as customers,
            avg(if(is_repeat_customer, 1, 0))                              as repeat_rate,
            avg(lifetime_revenue)                                          as avg_clv,
            safe_divide(sum(if(clv_decile = 10, lifetime_revenue, 0)),
                        sum(lifetime_revenue))                             as top10_share,
            safe_divide(sum(repeat_revenue), sum(lifetime_revenue))        as repeat_revenue_share
        from {marts('agg_customer_clv')}
    """).iloc[0]

    retention = run(f"""
        select
            months_since_first,
            safe_divide(sum(active_customers), sum(cohort_size)) as retention_rate,
            sum(cohort_size)                                     as cohort_people
        from {marts('agg_customer_cohort')}
        where is_in_analysis_window
          and cohort_year_month between '{month_range[0]}' and '{month_range[1]}'
          and months_since_first between 0 and 12
        group by months_since_first
        order by months_since_first
    """)
    month_12 = retention.loc[retention.months_since_first == 12, "retention_rate"]

    tiles = [
        ("Customers", count(clv_head.customers), "people with at least one kept order"),
        ("Repeat-purchase rate", pct(clv_head.repeat_rate, 2),
         "bought more than once, ever"),
        ("Average lifetime value", money(clv_head.avg_clv), "realised spend per person"),
        ("Top 10% of customers", pct(clv_head.top10_share),
         "of all customer revenue"),
        ("Still buying after 12 months",
         pct(month_12.iloc[0], 2) if not month_12.empty else "—",
         "of each cohort, weighted average"),
    ]
    for column, (label, value, note) in zip(st.columns(5), tiles):
        column.metric(label, value)
        column.caption(note)

    st.divider()
    st.markdown("#### 1. Retention curve: how many come back, and when?")
    curve = retention[retention.months_since_first > 0]
    st.altair_chart(
        alt.Chart(curve).mark_line(color=NAVY, point=True, strokeWidth=2.5).encode(
            x=alt.X("months_since_first:O", title="months after first purchase"),
            y=alt.Y("retention_rate:Q", title="share of cohort buying that month",
                    axis=alt.Axis(format=".2%")),
            tooltip=[alt.Tooltip("months_since_first:O", title="month"),
                     alt.Tooltip("retention_rate:Q", title="retention", format=".2%")],
        ).properties(height=300),
        width="stretch",
    )
    st.caption(
        "Month 0 (100% by definition) is left off so the scale is readable. Fewer than "
        "one customer in a hundred buys again in any later month: Olist is an "
        "acquisition business, not a retention business, today."
    )

    st.markdown("#### 2. Cohort heatmap")
    cohorts = run(f"""
        select cohort_year_month, months_since_first, retention_rate,
               cohort_size, active_customers
        from {marts('agg_customer_cohort')}
        where is_in_analysis_window
          and cohort_year_month between '{month_range[0]}' and '{month_range[1]}'
          and months_since_first between 1 and 12
          and cohort_size >= {int(min_orders)}
    """)
    st.altair_chart(
        alt.Chart(cohorts).mark_rect().encode(
            x=alt.X("months_since_first:O", title="months after first purchase"),
            y=alt.Y("cohort_year_month:O", title="first-purchase month"),
            color=alt.Color("retention_rate:Q", title="retention",
                            scale=alt.Scale(scheme="blues"),
                            legend=alt.Legend(format=".1%")),
            tooltip=[alt.Tooltip("cohort_year_month:O", title="cohort"),
                     alt.Tooltip("months_since_first:O", title="month"),
                     alt.Tooltip("cohort_size:Q", title="cohort size", format=","),
                     alt.Tooltip("active_customers:Q", title="came back", format=","),
                     alt.Tooltip("retention_rate:Q", title="retention", format=".2%")],
        ).properties(height=480),
        width="stretch",
    )
    st.caption(
        f"Cohorts smaller than {int(min_orders)} people are hidden (sidebar setting). "
        "Late cohorts have fewer columns because the export ends in 2018."
    )

    st.divider()
    st.markdown("#### 3. Where the value sits")
    deciles = run(f"""
        select
            clv_decile,
            count(*)              as customers,
            min(lifetime_revenue) as min_clv,
            avg(lifetime_revenue) as avg_clv,
            sum(lifetime_revenue) as revenue,
            avg(if(is_repeat_customer, 1, 0)) as repeat_rate
        from {marts('agg_customer_clv')}
        group by clv_decile
        order by clv_decile desc
    """)
    deciles["revenue_share"] = deciles.revenue / deciles.revenue.sum()
    st.altair_chart(
        alt.Chart(deciles).mark_bar(color=NAVY).encode(
            x=alt.X("clv_decile:O", title="lifetime-value decile (10 = top 10%)",
                    sort="descending"),
            y=alt.Y("revenue_share:Q", title="share of revenue", axis=alt.Axis(format="%")),
            tooltip=[alt.Tooltip("clv_decile:O", title="decile"),
                     alt.Tooltip("revenue_share:Q", title="share", format=".1%"),
                     alt.Tooltip("min_clv:Q", title="from R$", format=",.0f"),
                     alt.Tooltip("avg_clv:Q", title="avg R$", format=",.0f"),
                     alt.Tooltip("repeat_rate:Q", title="repeat rate", format=".1%")],
        ).properties(height=300),
        width="stretch",
    )

    st.divider()
    st.markdown("#### 4. Does the first payment predict the customer? (B + D)")
    st.caption(
        "Customers grouped by how they paid for their **first** order, so cause comes "
        "before effect: a returning customer has more chances to use instalments, and "
        "grouping on 'ever used instalments' would inflate the link."
    )
    by_first = run(f"""
        select
            first_installment_band,
            count(*)                            as customers,
            avg(if(is_repeat_customer, 1, 0))   as repeat_rate,
            avg(lifetime_revenue)               as avg_clv,
            avg(first_order_revenue)            as avg_first_order
        from {marts('agg_customer_clv')}
        where first_payment_type = 'credit_card'
        group by first_installment_band
        order by first_installment_band
    """)
    left, right = st.columns(2)
    with left:
        st.altair_chart(
            alt.Chart(by_first).mark_bar(color=ACCENT).encode(
                y=alt.Y("first_installment_band:N", title=None, sort=None),
                x=alt.X("repeat_rate:Q", title="repeat-purchase rate",
                        axis=alt.Axis(format=".1%")),
                tooltip=[alt.Tooltip("first_installment_band:N", title="first order"),
                         alt.Tooltip("customers:Q", format=","),
                         alt.Tooltip("repeat_rate:Q", format=".2%")],
            ).properties(height=220, title="Came back at least once"),
            width="stretch",
        )
    with right:
        st.altair_chart(
            alt.Chart(by_first).mark_bar(color=NAVY).encode(
                y=alt.Y("first_installment_band:N", title=None, sort=None),
                x=alt.X("avg_clv:Q", title="average lifetime value (R$)"),
                tooltip=[alt.Tooltip("first_installment_band:N", title="first order"),
                         alt.Tooltip("avg_clv:Q", title="avg CLV", format=",.0f"),
                         alt.Tooltip("avg_first_order:Q", title="avg first order",
                                     format=",.0f")],
            ).properties(height=220, title="Lifetime value"),
            width="stretch",
        )
    if len(by_first) >= 2:
        lo, hi = by_first.iloc[0], by_first.iloc[-1]
        st.info(
            f"Credit-card customers whose first order used **{hi.first_installment_band[3:]}** "
            f"came back at {pct(hi.repeat_rate, 1)} vs {pct(lo.repeat_rate, 1)} for a "
            # "\$": two unescaped dollar signs in one markdown string render the
            # text between them as a LaTeX formula and swallow both "$".
            f"{lo.first_installment_band[3:].lower()}, and are worth "
            f"{money(hi.avg_clv).replace('$', chr(92) + '$')} vs "
            f"{money(lo.avg_clv).replace('$', chr(92) + '$')} over their lifetime. An association, not proof that "
            "instalments cause loyalty — but a clear case for testing instalment offers "
            "as a retention lever.",
            icon="💡",
        )



# --------------------------------------------------------------------------- #
# RFM SEGMENTS  (business case B)
# --------------------------------------------------------------------------- #
with tab_segments:
    st.subheader("Which customers deserve which action?")
    st.caption(
        "Reads `agg_customer_rfm`: one row per person, recency measured against the "
        f"snapshot date {SNAPSHOT_DATE} (not today), quintile scores 1–5 on recency, "
        "frequency and monetary value. Segment names map to an action. All periods; "
        "the sidebar filters do not apply."
    )

    segments = run(f"""
        select
            rfm_segment,
            count(*)                                    as customers,
            sum(monetary)                               as revenue,
            avg(monetary)                               as avg_monetary,
            avg(frequency)                              as avg_frequency,
            avg(recency_days)                           as avg_recency_days,
            avg(if(frequency > 1, 1, 0))                as repeat_rate,
            avg(avg_review_score)                       as avg_review,
            avg(late_rate)                              as avg_late_rate,
            countif(is_high_value_with_late_delivery)   as high_value_late
        from {marts('agg_customer_rfm')}
        group by rfm_segment
        order by rfm_segment
    """)
    segments["share_of_customers"] = segments.customers / segments.customers.sum()
    segments["share_of_revenue"] = segments.revenue / segments.revenue.sum()

    at_risk = segments[segments.rfm_segment.str.startswith("3.")]
    tiles = [
        ("Segments", count(len(segments)), "action-oriented RFM groups"),
        ("Champions",
         count(segments.loc[segments.rfm_segment.str.startswith("1."), "customers"].sum()),
         "recent, repeat, high spend"),
        ("At risk, high value", count(at_risk.customers.sum()),
         f"{pct(at_risk.share_of_revenue.sum())} of revenue"),
        ("High value + a late delivery", count(segments.high_value_late.sum()),
         "m-score ≥ 4 with at least one late order"),
    ]
    for column, (label, value, note) in zip(st.columns(4), tiles):
        column.metric(label, value)
        column.caption(note)

    st.divider()
    # Stacked full-width rather than side by side: six long segment labels leave
    # a half-width bar chart room for a single axis tick on a laptop screen.
    long_shares = segments.melt(
        id_vars="rfm_segment", value_vars=["share_of_customers", "share_of_revenue"],
        var_name="measure", value_name="share",
    )
    long_shares["measure"] = long_shares.measure.str.replace("share_of_", "")
    st.markdown("#### 1. Customers vs revenue by segment")
    st.altair_chart(
        alt.Chart(long_shares).mark_bar().encode(
            y=alt.Y("rfm_segment:N", title=None, sort=None),
            x=alt.X("share:Q", title="share", axis=alt.Axis(format="%")),
            yOffset="measure:N",
            color=alt.Color("measure:N", title=None,
                            scale=alt.Scale(range=[MUTED, NAVY]),
                            legend=alt.Legend(orient="bottom")),
            tooltip=["rfm_segment:N", "measure:N",
                     alt.Tooltip("share:Q", format=".1%")],
        ).properties(height=340),
        width="stretch",
    )
    st.caption(
        "Grey bars are the share of people, navy bars the share of revenue. A navy bar "
        "longer than its grey one marks a segment worth more than its headcount."
    )

    st.markdown("#### 2. Spend vs recency")
    scatter = alt.Chart(segments).encode(
        # Extra room on the right so labels of the most dormant segments are not clipped.
        x=alt.X("avg_recency_days:Q", title="avg days since last order",
                scale=alt.Scale(domain=[0, float(segments.avg_recency_days.max()) * 1.45])),
        y=alt.Y("avg_monetary:Q", title="avg lifetime spend (R$)"),
    )
    st.altair_chart(
        alt.layer(
            scatter.mark_circle(color=ACCENT, opacity=0.8).encode(
                size=alt.Size("customers:Q", scale=alt.Scale(range=[80, 1500]), legend=None),
                tooltip=["rfm_segment:N",
                         alt.Tooltip("customers:Q", format=","),
                         alt.Tooltip("avg_monetary:Q", title="avg spend", format=",.0f"),
                         alt.Tooltip("avg_recency_days:Q", title="recency", format=",.0f"),
                         alt.Tooltip("repeat_rate:Q", title="repeat rate", format=".1%")],
            ),
            # Mid grey reads on both the light and the dark Streamlit theme.
            scatter.mark_text(align="left", dx=16, fontSize=12, color=MUTED)
            .encode(text="rfm_segment:N"),
        ).properties(height=340),
        width="stretch",
    )
    st.caption("Bubble size is the number of people in the segment.")

    st.dataframe(
        as_percent(segments, "share_of_customers", "share_of_revenue",
                   "repeat_rate", "avg_late_rate"),
        width="stretch", hide_index=True,
        column_config={
            "rfm_segment": "segment",
            "customers": st.column_config.NumberColumn("customers", format="%d"),
            "revenue": st.column_config.NumberColumn("revenue", format="R$ %.0f"),
            "avg_monetary": st.column_config.NumberColumn("avg spend", format="R$ %.0f"),
            "avg_frequency": st.column_config.NumberColumn("avg orders", format="%.2f"),
            "avg_recency_days": st.column_config.NumberColumn("avg recency (days)", format="%.0f"),
            "repeat_rate": st.column_config.NumberColumn("repeat rate", format="%.1f%%"),
            "avg_review": st.column_config.NumberColumn("avg review", format="%.2f★"),
            "avg_late_rate": st.column_config.NumberColumn("late rate", format="%.1f%%"),
            "high_value_late": st.column_config.NumberColumn("high value + late", format="%d"),
            "share_of_customers": st.column_config.NumberColumn("% customers", format="%.1f%%"),
            "share_of_revenue": st.column_config.NumberColumn("% revenue", format="%.1f%%"),
        },
    )
    st.info(
        "**Action map.** Champions → loyalty perks, protect delivery quality. "
        "High value, recent → second-purchase nudge inside the typical repurchase window. "
        "At risk, high value → personal win-back offer first: they carry outsized revenue. "
        "New / promising → onboarding sequence. Dormant, low value → low-cost reactivation only.",
        icon="🎯",
    )


# --------------------------------------------------------------------------- #
# SPEND OVER TIME  (business cases B + D)
# --------------------------------------------------------------------------- #
with tab_spend:
    st.subheader("How is spend changing, and who is it coming from?")
    st.caption(
        "Recomputed from `fct_orders` so the sidebar month and region filters apply. "
        "A person's first kept order is **new**; every later order is **returning**. "
        "The Data quality tab checks the unfiltered version against `agg_monthly_sales`."
    )
    monthly = run(f"""
        with seq as (
            select
                *,
                row_number() over (partition by customer_key
                                   order by order_purchased_at, order_id) = 1 as is_first_order
            from {marts('fct_orders')}
            where {KEPT_ORDERS_SQL}
        )
        select
            format_date('%Y-%m', order_purchase_date)               as year_month,
            count(*)                                                as orders,
            sum(order_revenue)                                      as revenue,
            sum(if(is_first_order, order_revenue, 0))               as new_revenue,
            sum(if(not is_first_order, order_revenue, 0))           as returning_revenue,
            countif(max_payment_installments > 1)                   as instalment_orders,
            safe_divide(sum(order_revenue), count(*))               as avg_order_value
        from seq
        where {WHERE}
        group by year_month
        order by year_month
    """)
    if monthly.empty:
        st.warning("No orders match these filters.")
    else:
        monthly["returning_share"] = monthly.returning_revenue / monthly.revenue
        monthly["instalment_share"] = monthly.instalment_orders / monthly.orders

        stacked = monthly.melt(
            id_vars="year_month", value_vars=["new_revenue", "returning_revenue"],
            var_name="source", value_name="revenue_part",
        )
        stacked["source"] = stacked.source.map(
            {"new_revenue": "first order", "returning_revenue": "repeat order"})
        st.markdown("#### 1. Monthly revenue: first orders vs repeat orders")
        st.altair_chart(
            alt.Chart(stacked).mark_bar().encode(
                x=alt.X("year_month:O", title="purchase month"),
                y=alt.Y("revenue_part:Q", title="revenue (R$)"),
                color=alt.Color("source:N", title=None,
                                scale=alt.Scale(range=[NAVY, ACCENT])),
                tooltip=["year_month:O", "source:N",
                         alt.Tooltip("revenue_part:Q", title="R$", format=",.0f")],
            ).properties(height=320),
            width="stretch",
        )
        st.caption(
            f"Repeat orders are {pct(monthly.returning_revenue.sum() / monthly.revenue.sum())} "
            "of revenue in the selected window: growth is almost entirely new-customer acquisition."
        )

        st.markdown("#### 2. Average order value and instalment usage")
        base = alt.Chart(monthly).encode(alt.X("year_month:O", title="purchase month"))
        st.altair_chart(
            alt.layer(
                base.mark_line(color=NAVY, point=True, strokeWidth=2.5).encode(
                    y=alt.Y("avg_order_value:Q", title="average order value (R$)"),
                    tooltip=["year_month:O",
                             alt.Tooltip("avg_order_value:Q", title="AOV", format=",.2f")],
                ),
                base.mark_line(color=ACCENT, point=True, strokeDash=[4, 3]).encode(
                    y=alt.Y("instalment_share:Q", title="orders paid in instalments",
                            axis=alt.Axis(format="%")),
                    tooltip=["year_month:O",
                             alt.Tooltip("instalment_share:Q", title="instalment share",
                                         format=".1%")],
                ),
            ).resolve_scale(y="independent").properties(
                height=320, title="Solid: AOV · dashed: share of orders in instalments"),
            width="stretch",
        )


# --------------------------------------------------------------------------- #
# INSTALMENTS  (business case D)
# --------------------------------------------------------------------------- #
with tab_instalments:
    st.subheader("Does offering instalments increase basket size?")
    st.caption(
        "Reads `agg_installment_basket`, built from `fct_orders` where payments are "
        "already collapsed to one row per order, so revenue cannot fan out across payment "
        "records. All periods and regions; the sidebar filters do not apply."
    )

    basket = run(f"""
        select payment_type, installments, installment_band, order_count, customers,
               revenue, avg_order_value, median_order_value, avg_items_per_order,
               late_rate, avg_review_score, is_reportable
        from {marts('agg_installment_basket')}
    """)
    card = basket[basket.payment_type == "credit_card"]

    bands = (
        card.groupby("installment_band", as_index=False)
        .agg(orders=("order_count", "sum"), revenue=("revenue", "sum"))
    )
    bands["avg_order_value"] = bands.revenue / bands.orders
    single = bands.loc[bands.installment_band == "1. Single payment", "avg_order_value"]
    long_ = bands.loc[bands.installment_band == "4. 7+ instalments", "avg_order_value"]
    card_orders = card.order_count.sum()
    instalment_orders = card.loc[card.installments > 1, "order_count"].sum()

    tiles = [
        ("Card orders paid in instalments", pct(instalment_orders / card_orders),
         f"{count(instalment_orders)} of {count(card_orders)} card orders"),
        ("AOV, single payment", money(single.iloc[0]) if not single.empty else "—",
         "credit card, 0–1 instalments"),
        ("AOV, 7+ instalments", money(long_.iloc[0]) if not long_.empty else "—",
         "credit card"),
        ("Basket multiple",
         f"{long_.iloc[0] / single.iloc[0]:.1f}×" if not (single.empty or long_.empty) else "—",
         "7+ instalments vs single payment"),
    ]
    for column, (label, value, note) in zip(st.columns(4), tiles):
        column.metric(label, value)
        column.caption(note)

    st.divider()
    st.markdown("#### 1. Average order value by instalment band (credit card)")
    st.altair_chart(
        alt.Chart(bands).mark_bar(color=NAVY).encode(
            x=alt.X("installment_band:N", title=None, sort=None,
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y("avg_order_value:Q", title="average order value (R$)"),
            tooltip=[alt.Tooltip("installment_band:N", title="band"),
                     alt.Tooltip("orders:Q", format=","),
                     alt.Tooltip("avg_order_value:Q", title="AOV", format=",.2f")],
        ).properties(height=320),
        width="stretch",
    )

    st.markdown("#### 2. Every instalment count")
    detail = card[card.is_reportable].sort_values("installments")
    sb = alt.Chart(detail).encode(alt.X("installments:O", title="instalments"))
    st.altair_chart(
        alt.layer(
            sb.mark_bar(color=MUTED, opacity=0.5).encode(
                y=alt.Y("order_count:Q", title="orders"),
            ),
            sb.mark_line(color=ACCENT, point=True, strokeWidth=2.5).encode(
                y=alt.Y("avg_order_value:Q", title="average order value (R$)"),
                tooltip=[alt.Tooltip("installments:O"),
                         alt.Tooltip("order_count:Q", title="orders", format=","),
                         alt.Tooltip("avg_order_value:Q", title="AOV", format=",.2f"),
                         alt.Tooltip("median_order_value:Q", title="median", format=",.2f"),
                         alt.Tooltip("avg_items_per_order:Q", title="items/order",
                                     format=".2f")],
            ),
        ).resolve_scale(y="independent")
        .properties(height=320, title="Bars: order volume · line: average order value"),
        width="stretch",
    )
    st.caption(
        "Instalment counts with fewer than 30 orders are hidden "
        "(dbt var `min_orders_for_reporting`). Items per order barely moves while order value "
        "climbs, so longer instalments go with **more expensive items**, not fuller baskets."
    )

    st.markdown("#### 3. By payment type")
    by_type = (
        basket.groupby("payment_type", as_index=False)
        .agg(orders=("order_count", "sum"), revenue=("revenue", "sum"))
        .sort_values("orders", ascending=False)
    )
    by_type["avg_order_value"] = by_type.revenue / by_type.orders
    by_type["share_of_orders"] = by_type.orders / by_type.orders.sum()
    st.dataframe(
        as_percent(by_type, "share_of_orders"),
        width="stretch", hide_index=True,
        column_config={
            "payment_type": "payment type",
            "orders": st.column_config.NumberColumn("orders", format="%d"),
            "revenue": st.column_config.NumberColumn("revenue", format="R$ %.0f"),
            "avg_order_value": st.column_config.NumberColumn("AOV", format="R$ %.2f"),
            "share_of_orders": st.column_config.NumberColumn("share of orders",
                                                             format="%.1f%%"),
        },
    )

    st.warning(
        "**Association, not causation.** Customers often choose more instalments "
        "*because* the item is expensive, at least as often as instalments make them "
        "spend more. Proving the causal effect needs an experiment (e.g. offering "
        "longer instalments to a random half of checkouts).",
        icon="⚠️",
    )


# --------------------------------------------------------------------------- #
# DATA QUALITY
# --------------------------------------------------------------------------- #
with tab_quality:
    st.subheader("Can these numbers be trusted?")
    st.caption(
        "A dashboard is only as credible as the pipeline behind it. These checks run "
        "live against the warehouse, and they are the same assertions the dbt build "
        "enforces on every run."
    )

    recon = run(f"""
        select
            (select round(sum(item_price), 2) from {staging('stg_order_items')})  as staging_revenue,
            (select round(sum(item_price), 2) from {marts('fct_order_items')})    as fact_item_revenue,
            (select round(sum(order_revenue), 2) from {marts('fct_orders')})      as fact_order_revenue,
            (select count(distinct order_id) from {staging('stg_orders')})        as staging_orders,
            (select count(*) from {marts('fct_orders')})                          as fact_order_rows,
            (select count(distinct customer_key) from {marts('fct_orders')}
              where not is_excluded_from_kpis)                                    as kept_people,
            (select count(distinct source_customer_id) from {marts('fct_orders')}
              where not is_excluded_from_kpis)                                    as kept_customer_ids,
            (select count(*) from {marts('agg_customer_rfm')})                    as rfm_rows,
            (select count(*) from {marts('agg_customer_clv')})                    as clv_rows,
            (select sum(cohort_size) from {marts('agg_customer_cohort')}
              where months_since_first = 0)                                       as cohort_people,
            (select countif(retention_rate != 1) from {marts('agg_customer_cohort')}
              where months_since_first = 0)                                       as bad_month_zero,
            (select sum(order_count) from {marts('agg_installment_basket')})      as basket_orders,
            (select round(sum(revenue), 2) from {marts('agg_installment_basket')}) as basket_revenue,
            (select count(*) from {marts('fct_orders')}
              where not is_excluded_from_kpis)                                    as kept_orders,
            (select round(sum(order_revenue), 2) from {marts('fct_orders')}
              where not is_excluded_from_kpis)                                    as kept_revenue
    """).iloc[0]

    revenue_ok = recon.staging_revenue == recon.fact_item_revenue == recon.fact_order_revenue
    orders_ok = recon.staging_orders == recon.fact_order_rows
    # Compared against people with at least one KEPT order, the same denominator
    # as the dbt test assert_rfm_uses_person_grain. Comparing against all of
    # dim_customer fails by design: 1,106 people placed only canceled or
    # unavailable orders and have no RFM row to compute.
    rfm_ok = recon.kept_people == recon.rfm_rows < recon.kept_customer_ids
    clv_ok = recon.clv_rows == recon.rfm_rows == recon.cohort_people and recon.bad_month_zero == 0
    basket_ok = (recon.basket_orders == recon.kept_orders
                 and recon.basket_revenue == recon.kept_revenue)

    # The Spend-over-time tab recomputes monthly revenue against fct_orders so it
    # can be filtered. This proves the unfiltered recomputation still agrees with
    # the pre-aggregated model, so the app cannot silently drift from the pipeline.
    agg_sales = run(f"""
        select round(sum(revenue), 2) as revenue,
               round(sum(returning_customer_revenue), 2) as returning_revenue
        from {marts('agg_monthly_sales')}
    """).iloc[0]
    app_sales = run(f"""
        with seq as (
            select order_revenue,
                   row_number() over (partition by customer_key
                                      order by order_purchased_at, order_id) > 1 as is_repeat
            from {marts('fct_orders')}
            where {KEPT_ORDERS_SQL}
        )
        select round(sum(order_revenue), 2) as revenue,
               round(sum(if(is_repeat, order_revenue, 0)), 2) as returning_revenue
        from seq
    """).iloc[0]
    sales_ok = (abs(agg_sales.revenue - app_sales.revenue) < 0.01
                and abs(agg_sales.returning_revenue - app_sales.returning_revenue) < 0.01)
    checks = pd.DataFrame([
        {"check": "Revenue reconciles: staging = fct_order_items = fct_orders",
         "ok": revenue_ok,
         "detail": f"{recon.staging_revenue:,.2f} / {recon.fact_item_revenue:,.2f} / {recon.fact_order_revenue:,.2f}"},
        {"check": "fct_orders is at one row per order",
         "ok": orders_ok,
         "detail": f"{count(recon.staging_orders)} staging orders / {count(recon.fact_order_rows)} fact rows"},
        {"check": "RFM is keyed on the person, not the per-order id",
         "ok": rfm_ok,
         "detail": f"{count(recon.kept_people)} people / {count(recon.rfm_rows)} RFM rows "
                   f"/ {count(recon.kept_customer_ids)} customer_ids"},
        {"check": "CLV and cohort models cover exactly the RFM population; month-0 retention = 100%",
         "ok": clv_ok,
         "detail": f"{count(recon.clv_rows)} CLV / {count(recon.rfm_rows)} RFM "
                   f"/ {count(recon.cohort_people)} cohort people"},
        {"check": "Instalment basket reconciles to fct_orders (no payment fan-out)",
         "ok": basket_ok,
         "detail": f"{count(recon.basket_orders)} / {count(recon.kept_orders)} orders · "
                   f"{recon.basket_revenue:,.2f} / {recon.kept_revenue:,.2f}"},
        {"check": "This dashboard's monthly spend agrees with agg_monthly_sales",
         "ok": sales_ok,
         "detail": f"app {app_sales.revenue:,.2f} / {app_sales.returning_revenue:,.2f} repeat "
                   f"vs model {agg_sales.revenue:,.2f} / {agg_sales.returning_revenue:,.2f}"},
    ])

    # Rendered as markdown rather than st.dataframe on purpose: the data grid
    # sizes its columns to content and collapses a four-row status readout into
    # something unreadable. A grid is for exploring data; this is a verdict.
    st.markdown(
        "| | Check | Observed |\n|:--:|---|---|\n"
        + "\n".join(
            f"| {'✅' if row.ok else '❌'} | {row.check} | `{row.detail}` |"
            for row in checks.itertuples()
        )
    )

    if checks.ok.all():
        st.success(
            "All live checks pass. Revenue is not inflated by any join, the fact table "
            "is at its declared grain, segmentation, lifetime value and cohorts are at "
            "person grain over the same population, and this app's numbers match the "
            "tested models.",
            icon="✅",
        )
    else:
        st.error(
            "A reconciliation check failed. Do not present these figures — investigate "
            "with `make build` and read the failing dbt test first.",
            icon="🚨",
        )

    st.divider()
    st.markdown("#### What the pipeline enforces on every build")
    st.markdown(
        """
| Gate | Tool | Blocks |
|---|---|---|
| **1 — File validation** | Great Expectations, before load | Column set, row count vs manifest, non-null keys, money ranges, categorical domains. A malformed export never reaches BigQuery. |
| **2 — Model contracts** | dbt tests | Uniqueness, referential integrity, accepted values, numeric ranges, person grain for every customer model, payment fan-out, source-to-mart revenue reconciliation. |

Severity is assigned deliberately: **error** blocks publication, **warn** publishes
with an explanation (voucher payments legitimately break the payment-total identity,
so making that an error would produce a permanently red build everyone ignores).

Full definitions: `dbt/olist/models/marts/_olist__marts.yml`
"""
    )

    with st.expander("Known limitations — read before quoting any figure"):
        st.markdown(
            f"""
- **Static export**, September 2016 – October 2018. Recency is measured against
  {SNAPSHOT_DATE}, not today. There is no genuine freshness dimension.
- **Sparse edge months** are excluded from the month selector, so a partial month
  cannot be mistaken for a demand collapse.
- **Correlation, not causation.** Instalments are *associated* with bigger baskets
  and higher repeat rates; customers choose instalments because an item is expensive
  at least as often as instalments make them spend more.
- **No cost data**, so margin cannot be computed. Every recommendation is framed on
  revenue and retention, never on profit.
- **Realised CLV**, not a forecast: with ~97% one-time buyers there is too little
  repeat behaviour to fit a predictive model honestly.
- **Voucher payments** legitimately break the payment-total identity; tested at warn
  severity and reported openly rather than coerced.
""" 
        )

st.divider()
st.caption(
    "Big Data Module 2 · Olist customer value, retention and instalments (cases B + D) · "
    "every figure sourced from the tested marts layer"
)
