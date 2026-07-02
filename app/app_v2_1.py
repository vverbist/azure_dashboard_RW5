# -*- coding: utf-8 -*-
"""
RW5 Revenue Dashboard Streamlit app.

The business logic lives in app_core so this app can coexist with the
FastAPI/frontend version without duplicating calculations.
"""

import calendar
import os
import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core.anomalies import build_anomaly_table
from app_core.benchmarks import summarize_greenchoice, summarize_strike_price
from app_core.calculations import aggregate_values, calculate_summary_table, make_variance_table, resample_df
from app_core.chart_data import greenchoice_bridge_components, revenue_bridge_components
from app_core.dashboard import (
    DashboardSettings,
    build_executive_narrative,
    format_period_label,
    make_delta_help,
    make_status_label,
    prepare_dashboard_frames,
    recognized_columns_table,
    selected_assumptions_table,
)
from app_core.formatting import format_generic_metric_table, format_summary_table, format_value, format_variance_table
from app_core.metadata import (
    ANOMALY_SPECS,
    CHART_GROUPS,
    EPEX_PRICE_COL,
    GREENCHOICE_VOLUME_COL,
    NOMINATION_VOLUME_COL,
    TIMESTAMP_COLUMNS,
    infer_unit,
    pretty_name,
)
from app_core.monthly import make_monthly_chart_source, make_monthly_kpi_table, make_monthly_numeric_table
from app_core.storage import StorageConfigurationError, list_csv_blobs as storage_list_csv_blobs, read_blob_csv as storage_read_blob_csv


st.set_page_config(page_title="RW5 Revenue Dashboard", page_icon="⚡", layout="wide")

BRAND = {
    "blue": "#1673E6",
    "blue_dark": "#004B9B",
    "navy": "#002B5C",
    "green": "#95C800",
    "green_dark": "#6FA000",
    "sky": "#7DB7FF",
    "soft_blue": "#EAF3FF",
    "soft_green": "#F3FAE3",
    "border": "#DCE7F5",
    "text": "#002B5C",
    "muted": "#52657A",
}


def inject_brand_css():
    st.markdown(
        f"""
        <style>
        :root {{
            --brand-blue: {BRAND['blue']};
            --brand-blue-dark: {BRAND['blue_dark']};
            --brand-navy: {BRAND['navy']};
            --brand-green: {BRAND['green']};
            --brand-soft-blue: {BRAND['soft_blue']};
            --brand-soft-green: {BRAND['soft_green']};
            --brand-border: {BRAND['border']};
        }}

        .stApp {{
            background:
                radial-gradient(circle at top right, rgba(149, 200, 0, 0.08), transparent 32rem),
                linear-gradient(180deg, #FFFFFF 0%, #F7FAFE 100%);
            color: var(--brand-navy);
        }}

        section[data-testid="stSidebar"] {{
            background: linear-gradient(180deg, var(--brand-blue-dark) 0%, #003B7C 55%, #002B5C 100%);
            border-right: 1px solid rgba(255, 255, 255, 0.12);
        }}
        section[data-testid="stSidebar"] * {{ color: #FFFFFF !important; }}
        section[data-testid="stSidebar"] div[data-baseweb="select"] * {{ color: var(--brand-navy) !important; }}
        section[data-testid="stSidebar"] input {{ color: var(--brand-navy) !important; }}
        section[data-testid="stSidebar"] label p {{ font-weight: 600; }}

        .brand-header {{
            padding: 1.35rem 1.5rem;
            margin: 0 0 1.25rem 0;
            border-radius: 18px;
            background: linear-gradient(135deg, rgba(22, 115, 230, 0.12), rgba(149, 200, 0, 0.12));
            border: 1px solid var(--brand-border);
            box-shadow: 0 8px 24px rgba(0, 43, 92, 0.08);
        }}
        .brand-eyebrow {{
            color: var(--brand-green-dark);
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            font-size: 0.78rem;
            margin-bottom: 0.25rem;
        }}
        .brand-title {{
            color: var(--brand-navy);
            font-size: 2.15rem;
            line-height: 1.1;
            font-weight: 850;
            margin: 0;
        }}
        .brand-subtitle {{
            color: {BRAND['muted']};
            margin-top: 0.4rem;
            font-size: 1.02rem;
        }}

        div[data-testid="stMetric"] {{
            background: #FFFFFF;
            border: 1px solid var(--brand-border);
            border-radius: 16px;
            padding: 1rem 1rem;
            box-shadow: 0 6px 18px rgba(0, 43, 92, 0.07);
        }}
        div[data-testid="stMetricLabel"] p {{
            color: var(--brand-navy) !important;
            font-weight: 700;
        }}
        div[data-testid="stMetricValue"] {{ color: var(--brand-navy); }}
        div[data-testid="stMetricDelta"] {{ color: var(--brand-green-dark); }}

        div[data-testid="stTabs"] button[aria-selected="true"] {{
            color: var(--brand-blue) !important;
            border-bottom-color: var(--brand-green) !important;
        }}

        div[data-testid="stDataFrame"], div[data-testid="stTable"] {{
            border-radius: 14px;
            overflow: hidden;
        }}

        .stButton button, .stDownloadButton button {{
            border-radius: 10px;
            border: 1px solid var(--brand-blue);
            color: var(--brand-blue-dark);
            font-weight: 700;
        }}
        .stDownloadButton button:hover, .stButton button:hover {{
            border-color: var(--brand-green);
            color: var(--brand-green-dark);
        }}

        h1, h2, h3 {{ color: var(--brand-navy); }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_brand_header():
    st.markdown(
        """
        <div class="brand-header">
            <div class="brand-eyebrow">Onensys onsite energy systems</div>
            <h1 class="brand-title">RW5 Revenue Dashboard</h1>
            <div class="brand-subtitle">Decision-support layer for EPEX, imbalance, revenue, and capture diagnostics.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_brand():
    logo_candidates = [
        "assets/onensys_logo.png",
        "assets/logo.png",
        "onensys_logo.png",
    ]
    for logo_path in logo_candidates:
        if os.path.exists(logo_path):
            st.sidebar.image(logo_path, width=220)
            return
    st.sidebar.markdown("### ONENSYS")
    st.sidebar.caption("Onsite energy systems")


def streamlit_connection_string() -> str | None:
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if conn_str:
        return conn_str
    try:
        return st.secrets["AZURE_STORAGE_CONNECTION_STRING"]
    except Exception:
        return None


@st.cache_data(ttl=300)
def list_csv_blobs(prefix: str, connection_string: str | None):
    return storage_list_csv_blobs(prefix, connection_string=connection_string)


@st.cache_data(ttl=300)
def read_blob_csv(blob_name: str, connection_string: str | None):
    return storage_read_blob_csv(blob_name, connection_string=connection_string)


def month_bounds(year, month, min_date, max_date):
    start = pd.Timestamp(year=year, month=month, day=1).date()
    end = pd.Timestamp(year=year, month=month, day=calendar.monthrange(year, month)[1]).date()
    return max(start, min_date), min(end, max_date)


def last_full_month_bounds(reference_date, min_date, max_date):
    first_of_reference_month = pd.Timestamp(reference_date).replace(day=1)
    last_full_month_end = (first_of_reference_month - pd.Timedelta(days=1)).date()
    last_full_month_start = last_full_month_end.replace(day=1)
    return max(last_full_month_start, min_date), min(last_full_month_end, max_date)


def color_for_series(name):
    n = str(name).lower()
    if "greenchoice" in n:
        return BRAND["green"]
    if "epex" in n:
        return BRAND["green_dark"]
    if "imbalance" in n:
        return BRAND["sky"]
    if "strike" in n or "below" in n:
        return "#F59E0B"
    if "volume" in n or "delivered" in n or "production" in n:
        return BRAND["blue"]
    if "capture" in n:
        return BRAND["blue_dark"]
    if "revenue" in n or "total" in n or "actual" in n:
        return BRAND["blue"]
    return BRAND["navy"]


def apply_brand_trace_colors(fig):
    for trace in fig.data:
        color = color_for_series(getattr(trace, "name", ""))
        trace_type = getattr(trace, "type", None)
        if trace_type == "bar":
            trace.update(marker={"color": color})
        elif trace_type == "scatter":
            trace.update(line={"color": color})
        elif trace_type == "waterfall":
            trace.update(
                increasing={"marker": {"color": BRAND["green"]}},
                decreasing={"marker": {"color": "#EF4444"}},
                totals={"marker": {"color": BRAND["blue"]}},
            )
    return fig


def style_plotly(fig, title=None, height=None):
    apply_brand_trace_colors(fig)
    fig.update_layout(
        template="plotly_white",
        title={"text": title, "x": 0.01, "xanchor": "left"} if title else None,
        hovermode="x unified",
        legend={"orientation": "h", "y": -0.22, "x": 0},
        margin={"l": 70, "r": 40, "t": 70 if title else 40, "b": 90},
        paper_bgcolor="rgba(255,255,255,0)",
        plot_bgcolor="#FFFFFF",
        font={"color": BRAND["navy"]},
        colorway=[BRAND["blue"], BRAND["green"], BRAND["sky"], BRAND["blue_dark"], BRAND["green_dark"]],
    )
    if height:
        fig.update_layout(height=height)
    fig.update_xaxes(showgrid=False, linecolor=BRAND["border"], tickfont={"color": BRAND["text"]})
    fig.update_yaxes(zeroline=True, zerolinewidth=1, gridcolor="#E8EEF6", linecolor=BRAND["border"], tickfont={"color": BRAND["text"]})
    return fig


def make_line_plot(df, time_col, cols, title, y_title=None, strike_price=None):
    fig = go.Figure()
    for col in cols:
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df[time_col],
                y=df[col],
                mode="lines",
                name=pretty_name(col),
                line={"width": 2},
            ))
    if strike_price is not None:
        fig.add_hline(
            y=strike_price,
            line_dash="dash",
            annotation_text=f"Strike: {strike_price:,.2f} €/MWh",
            annotation_position="top left",
        )
    fig.update_yaxes(title=y_title or "")
    return style_plotly(fig, title=title, height=430)


def make_bar_plot(df, time_col, cols, title, y_title="€"):
    fig = go.Figure()
    for col in cols:
        if col in df.columns:
            fig.add_trace(go.Bar(x=df[time_col], y=df[col], name=pretty_name(col)))
    fig.update_yaxes(title=y_title)
    fig.update_layout(barmode="relative")
    return style_plotly(fig, title=title, height=430)


def make_revenue_bridge(summary_table):
    components = revenue_bridge_components(summary_table)
    fig = go.Figure(go.Waterfall(
        name="Revenue bridge",
        orientation="v",
        measure=[row["measure"] for row in components],
        x=[row["label"] for row in components],
        y=[row["value"] for row in components],
        text=[row["text"] for row in components],
        textposition="outside",
        connector={"line": {"width": 1}},
    ))
    fig.update_yaxes(title="€")
    return fig


def make_greenchoice_bridge(df):
    components = greenchoice_bridge_components(df)
    if not components:
        return go.Figure()
    fig = go.Figure(go.Waterfall(
        name="Actual vs Greenchoice",
        measure=[row["measure"] for row in components],
        x=[row["label"] for row in components],
        y=[row["value"] for row in components],
        text=[row["text"] for row in components],
        textposition="outside",
        connector={"line": {"width": 1}},
    ))
    fig.update_yaxes(title="€")
    return style_plotly(fig, title="Actual revenue vs Greenchoice benchmark", height=430)


def make_monthly_kpi_bar_chart(chart_df, month_col, metric_col, title):
    fig = go.Figure()
    if chart_df.empty or metric_col not in chart_df.columns:
        return fig
    fig.add_trace(go.Bar(x=chart_df[month_col], y=chart_df[metric_col], name=metric_col))
    unit = ""
    if "EUR/MWh" in metric_col:
        unit = "€/MWh"
    elif "EUR" in metric_col:
        unit = "€"
    elif "MWh" in metric_col:
        unit = "MWh"
    fig.update_yaxes(title=unit)
    return style_plotly(fig, title=title, height=360)


def render_aggregate_metrics(df, value_cols, unit_map):
    values = aggregate_values(df, value_cols, unit_map)
    metric_cols = st.columns(min(len(value_cols), 5))
    for i, col in enumerate(value_cols):
        with metric_cols[i % len(metric_cols)]:
            st.metric(pretty_name(col), values[col])


def make_anomaly_download(table, label, file_name):
    if not table.empty:
        st.download_button(
            label=label,
            data=table.to_csv(index=False).encode("utf-8"),
            file_name=file_name,
            mime="text/csv",
            width="stretch",
        )


def render_metric_card(label, value, help_text=None, delta=None, delta_color="normal"):
    st.metric(label=label, value=value, delta=delta, help=help_text, delta_color=delta_color)


def render_executive_narrative(df, summary_table, variance_table):
    bullets = build_executive_narrative(df, summary_table, variance_table)
    if bullets:
        st.markdown("\n".join(f"- {item['text']}" for item in bullets))
    else:
        st.info("Not enough recognized columns to generate an executive summary.")


inject_brand_css()
render_brand_header()
render_sidebar_brand()

connection_string = streamlit_connection_string()
if not connection_string:
    st.error("AZURE_STORAGE_CONNECTION_STRING is not configured.")
    st.stop()

try:
    export_files = list_csv_blobs("exports/", connection_string)
except StorageConfigurationError as exc:
    st.error(str(exc))
    st.stop()

if not export_files:
    st.error("No YTD export files found in Blob Storage under exports/")
    st.stop()

selected_blob = export_files[-1]
raw_df = read_blob_csv(selected_blob, connection_string)
st.caption(f"YTD dataset: `{selected_blob}`")

timestamp_options = [c for c in TIMESTAMP_COLUMNS if c in raw_df.columns]
if not timestamp_options:
    st.error("The YTD export must contain a recognized timestamp column.")
    st.stop()

with st.sidebar:
    st.header("Controls")
    default_time_index = timestamp_options.index("timestamp_Ams") if "timestamp_Ams" in timestamp_options else 0
    time_col = st.selectbox("Timestamp", timestamp_options, index=default_time_index, key="v13_timestamp_column_selector")

raw_df[time_col] = pd.to_datetime(raw_df[time_col], errors="coerce")
parsed_df = raw_df.dropna(subset=[time_col]).sort_values(time_col)

min_date = parsed_df[time_col].min().date()
max_date = parsed_df[time_col].max().date()
available_months = sorted(parsed_df[time_col].dt.to_period("M").dropna().unique())
month_labels = [f"{p.year} - {calendar.month_name[p.month]}" for p in available_months]
month_lookup = dict(zip(month_labels, available_months))

with st.sidebar:
    quick_period_options = ["Custom range", "All data", "Last full month"] + month_labels
    quick_period = st.selectbox(
        "Quick period",
        quick_period_options,
        key="v13_quick_period",
        help="Selecting a period updates the calendar below. Use Custom range for manual dates.",
    )

    if quick_period == "All data":
        selected_date_range = (min_date, max_date)
    elif quick_period == "Last full month":
        selected_date_range = last_full_month_bounds(max_date, min_date, max_date)
    elif quick_period in month_lookup:
        selected_month = month_lookup[quick_period]
        selected_date_range = month_bounds(selected_month.year, selected_month.month, min_date, max_date)
    else:
        selected_date_range = (min_date, max_date)

    date_range_key = "v13_date_range_" + re.sub(r"[^0-9A-Za-z_]+", "_", quick_period).strip("_").lower()
    date_range = st.date_input("Date range", value=selected_date_range, min_value=min_date, max_value=max_date, key=date_range_key)
    rule = st.selectbox(
        "Resampling frequency",
        ["Original", "15min", "h", "D", "W", "ME", "YE"],
        format_func=lambda x: {"Original": "Original", "15min": "15 minutes", "h": "Hourly", "D": "Daily", "W": "Weekly", "ME": "Monthly", "YE": "Yearly"}[x],
        key="v13_resampling_frequency",
    )
    anomaly_n = st.slider("Rows in anomaly tables", min_value=5, max_value=30, value=10, step=5)

    st.header("Greenchoice settings")
    afslag_pct = st.number_input("Greenchoice afslag (%)", min_value=0.0, max_value=100.0, value=17.0, step=0.5, key="v13_gc_afslag_pct") / 100.0
    afslag_min = st.number_input("Greenchoice afslag floor (€/MWh)", value=10.0, step=0.5, key="v13_gc_afslag_min")
    gvo = st.number_input("GvO value (€/MWh)", value=0.0, step=0.10, key="v13_gc_gvo")

    st.header("Strike price")
    strike_price = st.number_input("Strike price for negative nomination revenue (€/MWh)", value=0.0, step=1.0, key="v13_strike_price")

start_date = None
end_date = None
if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
    start_date, end_date = date_range

settings = DashboardSettings(
    timestamp_col=time_col,
    start_date=start_date,
    end_date=end_date,
    resampling_rule=rule,
    greenchoice_afslag_pct=afslag_pct,
    greenchoice_afslag_floor=afslag_min,
    gvo_value=gvo,
    strike_price=strike_price,
)

df, ytd_analysis_df = prepare_dashboard_frames(raw_df, settings)
numeric_cols = [col for col in df.columns if col != time_col and pd.api.types.is_numeric_dtype(df[col])]
summary_table = calculate_summary_table(df)

st.header("Dashboard")

variance_table = make_variance_table(df)
gc_summary = summarize_greenchoice(df)
strike_summary = summarize_strike_price(df)

total_revenue = summary_table.loc["Revenue", "Total"]
rev_vs_epex = df["revenue_vs_epex_calc"].sum() if "revenue_vs_epex_calc" in df.columns else np.nan
rev_vs_greenchoice = df["revenue_vs_greenchoice_calc"].sum() if "revenue_vs_greenchoice_calc" in df.columns else np.nan
strike_revenue = df["strike_nomination_revenue"].sum() if "strike_nomination_revenue" in df.columns else np.nan
below_strike_count = int(df["is_below_strike"].sum()) if "is_below_strike" in df.columns else 0

summary_tab, monthly_tab, bridge_tab, anomaly_tab, timeseries_tab, quality_tab = st.tabs([
    "Executive summary",
    "Monthly overview",
    "Revenue bridge",
    "Anomalies",
    "Timeseries",
    "Data quality",
])

with summary_tab:
    st.subheader("Selected data")
    ctx1, ctx2, ctx3, ctx4 = st.columns(4)
    ctx1.metric("Period", format_period_label(df, time_col))
    ctx2.metric("Rows", f"{len(df):,}")
    ctx3.metric("Granularity", rule)
    ctx4.metric("Source", "YTD export")

    st.subheader("Headline KPIs")
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        render_metric_card("Total revenue", format_value(total_revenue, "€"), "Actual total revenue in the filtered period.")
    with k2:
        render_metric_card("Actual vs Greenchoice", format_value(rev_vs_greenchoice, "€"), make_delta_help(rev_vs_greenchoice, "Actual revenue beats the Greenchoice benchmark.", "Actual revenue is below the Greenchoice benchmark."), delta=make_status_label(rev_vs_greenchoice), delta_color="normal")
    with k3:
        render_metric_card("Actual vs EPEX", format_value(rev_vs_epex, "€"), make_delta_help(rev_vs_epex, "Actual revenue beats nominated EPEX revenue.", "Actual revenue is below nominated EPEX revenue."), delta=make_status_label(rev_vs_epex), delta_color="normal")
    with k4:
        render_metric_card("Below-strike revenue", format_value(strike_revenue, "€"), "Nomination revenue during periods where EPEX is below the configured strike price.", delta=f"{below_strike_count:,} periods", delta_color="inverse")

    st.subheader("So what?")
    render_executive_narrative(df, summary_table, variance_table)

    st.subheader("Commercial breakdown")
    st.dataframe(format_summary_table(summary_table), width="stretch")
    st.caption("Imbalance-total capture price uses absolute net imbalance volume in the denominator, so treat it as €/MWh of absolute imbalance exposure.")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("Download filtered data", df.to_csv(index=False).encode("utf-8"), "filtered_timeseries.csv", "text/csv", width="stretch")
    with c2:
        st.download_button("Download summary table", format_summary_table(summary_table).to_csv().encode("utf-8"), "summary_table.csv", "text/csv", width="stretch")
    with c3:
        if not variance_table.empty:
            st.download_button("Download variance table", format_variance_table(variance_table).to_csv(index=False).encode("utf-8"), "variance_table.csv", "text/csv", width="stretch")

with monthly_tab:
    st.subheader("Monthly KPI overview")
    st.caption("Full YTD export broken down by month, with a YTD total column on the right. This table is independent of the selected calendar filter above.")
    monthly_kpi_table = make_monthly_kpi_table(ytd_analysis_df, time_col)
    if monthly_kpi_table.empty:
        st.info("No monthly KPI overview available for the loaded YTD export.")
    else:
        st.dataframe(monthly_kpi_table, width="stretch", hide_index=True)
        st.download_button(
            "Download monthly KPI overview",
            monthly_kpi_table.to_csv(index=False).encode("utf-8"),
            "monthly_kpi_overview.csv",
            "text/csv",
            width="stretch",
        )

    monthly_numeric_table = make_monthly_numeric_table(ytd_analysis_df, time_col)
    monthly_chart_df = make_monthly_chart_source(ytd_analysis_df, time_col)
    if not monthly_chart_df.empty:
        st.subheader("Monthly bar charts")
        chart_metric_options = [c for c in monthly_chart_df.columns if c != "Month"]
        chart_defaults = [
            "Total revenue EUR",
            "Delivered volume MWh",
            "Capture price EUR/MWh",
        ]
        chart_cols = st.columns(3)
        for i, col in enumerate(chart_cols):
            with col:
                default_metric = chart_defaults[i] if chart_defaults[i] in chart_metric_options else chart_metric_options[0]
                metric = st.selectbox(
                    f"Chart {i + 1} KPI",
                    chart_metric_options,
                    index=chart_metric_options.index(default_metric),
                    key=f"v13_monthly_chart_metric_{i}",
                )
                st.plotly_chart(
                    make_monthly_kpi_bar_chart(monthly_chart_df, "Month", metric, metric.replace(" EUR", "").replace(" MWh", "")),
                    width="stretch",
                )

    with st.expander("Numeric monthly export", expanded=False):
        if not monthly_numeric_table.empty:
            st.dataframe(monthly_numeric_table, width="stretch", hide_index=True)
            st.download_button(
                "Download numeric monthly export",
                monthly_numeric_table.to_csv(index=False).encode("utf-8"),
                "monthly_kpi_numeric.csv",
                "text/csv",
                width="stretch",
            )

with bridge_tab:
    st.subheader("Revenue decomposition")
    left, right = st.columns([1.25, 1])
    with left:
        fig = make_revenue_bridge(summary_table)
        st.plotly_chart(style_plotly(fig, title="Revenue bridge", height=430), width="stretch")
    with right:
        st.markdown("**How to read this**")
        st.markdown(
            "This separates nominated EPEX revenue from imbalance revenue. "
            "Use it to see whether performance came from market exposure, imbalance exposure, or both."
        )
        st.dataframe(format_variance_table(variance_table), width="stretch", hide_index=True)

    st.subheader("Greenchoice benchmark")
    left, right = st.columns([1.25, 1])
    with left:
        if "greenchoice_revenue" in df.columns:
            st.plotly_chart(make_greenchoice_bridge(df), width="stretch")
        else:
            st.info("Greenchoice benchmark unavailable because the selected volume or EPEX price column is missing.")
    with right:
        if not gc_summary.empty:
            st.dataframe(format_generic_metric_table(gc_summary), width="stretch", hide_index=True)
        st.markdown("**Formula**  \nBenchmark revenue = delivered volume x max(EPEX - max(EPEX x afslag %, afslag floor) + GvO, 0).")

    st.subheader("Strike-price exposure")
    left, right = st.columns([1.25, 1])
    with left:
        if EPEX_PRICE_COL in df.columns:
            plot_cols = [EPEX_PRICE_COL]
            st.plotly_chart(make_line_plot(df, time_col, plot_cols, "EPEX price versus strike price", "€/MWh", strike_price=strike_price), width="stretch")
    with right:
        if not strike_summary.empty:
            st.dataframe(format_generic_metric_table(strike_summary), width="stretch", hide_index=True)
        st.markdown("This isolates nominated volume exposed to prices below the configured strike price.")

with anomaly_tab:
    st.subheader("Action-oriented anomaly finder")
    st.caption("Each row explains what is unusual, the approximate impact, and the context needed to investigate it.")

    anomaly_items = list(ANOMALY_SPECS.values())
    tabs = st.tabs([item["label"] for item in anomaly_items])
    for tab, item in zip(tabs, anomaly_items):
        with tab:
            st.markdown(f"**Focus:** {item['description']}")
            source_df = df[df["is_below_strike"]] if item["label"] == "Below strike" and "is_below_strike" in df.columns else df
            table = build_anomaly_table(source_df, time_col, item["metric"], anomaly_n, largest=item["largest"])
            st.dataframe(table, width="stretch", hide_index=True)
            make_anomaly_download(table, f"Download {item['label'].lower()} table", item["file_name"])

with timeseries_tab:
    st.subheader("Styled timeseries explorer")
    available_groups = {title: [c for c in cols if c in numeric_cols] for title, cols in CHART_GROUPS.items()}
    all_chart_cols = sorted(set(c for cols in available_groups.values() for c in cols))
    if all_chart_cols:
        plot_df = resample_df(df, time_col, all_chart_cols, rule)
        for title, cols in available_groups.items():
            if not cols:
                continue
            with st.container(border=True):
                st.markdown(f"### {title}")
                if title in ["Revenue components", "Revenue deltas"]:
                    st.plotly_chart(make_bar_plot(plot_df, time_col, cols, title, "€"), width="stretch")
                else:
                    y_unit = infer_unit(cols[0]) if cols else ""
                    st.plotly_chart(make_line_plot(plot_df, time_col, cols, title, y_unit, strike_price if title == "Prices and capture" else None), width="stretch")
                with st.expander("Aggregate values", expanded=False):
                    unit_map = {col: infer_unit(col) for col in cols}
                    render_aggregate_metrics(df, cols, unit_map)
    else:
        st.info("None of the predefined chart columns were found.")

with quality_tab:
    st.subheader("Data quality and assumptions")
    from app_core.quality import make_data_quality_table

    q = make_data_quality_table(df, time_col)
    st.dataframe(q, width="stretch", hide_index=True)

    st.subheader("Selected assumptions")
    st.dataframe(selected_assumptions_table(settings), width="stretch", hide_index=True)

    st.subheader("Recognized columns")
    st.dataframe(recognized_columns_table(df, time_col), width="stretch", hide_index=True)
