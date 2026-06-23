# -*- coding: utf-8 -*-
"""
Timeseries Viewer v1.2

Main additions vs v1.0:
- Data context and quality checks
- Revenue bridge / waterfall
- Benchmark and variance diagnostics
- Anomaly tables for decision support
- Greenchoice benchmark configuration
- Strike-price negative nomination revenue diagnostic
- Safer summary formatting for missing/NaN values
- Explicit column metadata overrides while keeping fallback inference
"""

import re
import os
import calendar
from io import BytesIO

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from azure.storage.blob import BlobServiceClient


CONTAINER_NAME = "rw5data-turbine-edmij-entsoe"

# Optional but recommended: keep critical business semantics out of fuzzy string logic.
COLUMN_METADATA = {
    "delivered_volume_mwh": {"unit": "MWh", "aggregation": "sum", "label": "Delivered volume"},
    "nominated_volume_mwh": {"unit": "MWh", "aggregation": "sum", "label": "Nominated volume"},
    "volume_long_mwh": {"unit": "MWh", "aggregation": "sum", "label": "Long imbalance volume"},
    "volume_short_mwh": {"unit": "MWh", "aggregation": "sum", "label": "Short imbalance volume"},
    "total_revenue": {"unit": "€", "aggregation": "sum", "label": "Total revenue"},
    "epex_revenue": {"unit": "€", "aggregation": "sum", "label": "EPEX revenue"},
    "imbalance_total_revenue": {"unit": "€", "aggregation": "sum", "label": "Total imbalance revenue"},
    "imbalance_long_revenue": {"unit": "€", "aggregation": "sum", "label": "Long imbalance revenue"},
    "imbalance_short_revenue": {"unit": "€", "aggregation": "sum", "label": "Short imbalance revenue"},
    "epex_eur_per_mwh": {"unit": "€/MWh", "aggregation": "mean", "label": "EPEX price"},
    "imbalance_long_eur_per_mwh": {"unit": "€/MWh", "aggregation": "mean", "label": "Long imbalance price"},
    "imbalance_short_eur_per_mwh": {"unit": "€/MWh", "aggregation": "mean", "label": "Short imbalance price"},
}

DIAGNOSTIC_METADATA = {
    "revenue_vs_epex_calc": {"unit": "€", "aggregation": "sum", "label": "Revenue vs EPEX"},
    "imbalance_volume_mwh_calc": {"unit": "MWh", "aggregation": "sum", "label": "Net imbalance volume"},
    "abs_imbalance_volume_mwh_calc": {"unit": "MWh", "aggregation": "sum", "label": "Absolute imbalance volume"},
    "capture_total_calc": {"unit": "€/MWh", "aggregation": "mean", "label": "Total capture"},
    "capture_epex_calc": {"unit": "€/MWh", "aggregation": "mean", "label": "EPEX capture"},
    "capture_spread_vs_epex_calc": {"unit": "€/MWh", "aggregation": "mean", "label": "Capture spread vs EPEX"},
    "greenchoice_afslag_eur_per_mwh": {"unit": "€/MWh", "aggregation": "mean", "label": "Greenchoice afslag"},
    "greenchoice_net_price_eur_per_mwh": {"unit": "€/MWh", "aggregation": "mean", "label": "Greenchoice net price"},
    "greenchoice_billable_price_eur_per_mwh": {"unit": "€/MWh", "aggregation": "mean", "label": "Greenchoice billable price"},
    "greenchoice_revenue": {"unit": "€", "aggregation": "sum", "label": "Greenchoice benchmark revenue"},
    "revenue_vs_greenchoice_calc": {"unit": "€", "aggregation": "sum", "label": "Revenue vs Greenchoice"},
    "strike_nomination_revenue": {"unit": "€", "aggregation": "sum", "label": "Nomination revenue below strike"},
}

COLUMN_METADATA.update(DIAGNOSTIC_METADATA)


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


inject_brand_css()
render_brand_header()
render_sidebar_brand()


def pretty_name(col):
    return COLUMN_METADATA.get(col, {}).get("label", col.replace("_", " ").title())


def infer_unit(col):
    if col in COLUMN_METADATA:
        return COLUMN_METADATA[col]["unit"]

    c = col.lower()
    if "eur_per_mwh" in c or "price" in c or "capture" in c:
        return "€/MWh"
    if "revenue" in c:
        return "€"
    if "mwh" in c or "volume" in c:
        return "MWh"
    if "performance" in c:
        return "ratio"
    if "share" in c:
        return "%"

    match = re.search(r"\[(.*?)\]|\((.*?)\)", col)
    if match:
        return match.group(1) or match.group(2)
    return "Other"


def agg_for_col(col):
    if col in COLUMN_METADATA:
        return COLUMN_METADATA[col]["aggregation"]

    c = col.lower()
    if "eur_per_mwh" in c or "capture" in c or "performance" in c or "share" in c:
        return "mean"
    if "mwh" in c or "volume" in c or "revenue" in c:
        return "sum"
    return "mean"


def format_value(value, unit, decimals=2):
    if pd.isna(value):
        return "-"
    if unit == "€":
        return f"€{value:,.0f}"
    if unit == "€/MWh":
        return f"{value:,.{decimals}f} €/MWh"
    if unit == "MWh":
        return f"{value:,.{decimals}f} MWh"
    if unit == "%":
        return f"{value:,.2%}" if abs(value) <= 1 else f"{value:,.2f}%"
    if unit == "ratio":
        return f"{value:,.3f}"
    return f"{value:,.2f}"


def safe_div(a, b):
    return a / b if b not in [0, None] and pd.notna(b) else np.nan


def existing(cols, df):
    return [c for c in cols if c in df.columns]


def resample_df(df, time_col, value_cols, rule):
    if not value_cols:
        return df[[time_col]].copy()
    if rule == "Original":
        return df[[time_col] + value_cols].copy()
    temp = df[[time_col] + value_cols].copy().set_index(time_col)
    agg_map = {col: agg_for_col(col) for col in value_cols}
    return temp.resample(rule).agg(agg_map).reset_index()


def aggregate_values(df, value_cols, unit_map):
    values = {}
    for col in value_cols:
        agg = agg_for_col(col)
        value = df[col].sum() if agg == "sum" else df[col].mean()
        values[col] = format_value(value, unit_map[col])
    return values


def render_aggregate_metrics(df, value_cols, unit_map):
    values = aggregate_values(df, value_cols, unit_map)
    metric_cols = st.columns(min(len(value_cols), 5))
    for i, col in enumerate(value_cols):
        with metric_cols[i % len(metric_cols)]:
            st.metric(pretty_name(col), values[col])


def axis_range_inputs(chart_title, units, df, value_cols, unit_map):
    ranges = {}
    if not units:
        return ranges
    with st.expander("Y-axis ranges", expanded=False):
        axis_cols = st.columns(len(units))
        for i, unit in enumerate(units):
            unit_value_cols = [c for c in value_cols if unit_map[c] == unit]
            min_default = float(df[unit_value_cols].min().min()) if unit_value_cols else 0.0
            max_default = float(df[unit_value_cols].max().max()) if unit_value_cols else 1.0
            with axis_cols[i]:
                st.markdown(f"**{unit}**")
                use_auto = st.checkbox("Auto", value=True, key=f"{chart_title}_{unit}_auto")
                if use_auto:
                    ranges[unit] = None
                else:
                    ymin = st.number_input("Min", value=min_default, key=f"{chart_title}_{unit}_min")
                    ymax = st.number_input("Max", value=max_default, key=f"{chart_title}_{unit}_max")
                    ranges[unit] = [ymin, ymax]
    return ranges


def make_multi_axis_plot(df, time_col, value_cols, unit_map, axis_ranges):
    fig = go.Figure()
    units = []
    for col in value_cols:
        unit = unit_map[col]
        if unit not in units:
            units.append(unit)

    axis_map = {unit: "y" if i == 0 else f"y{i + 1}" for i, unit in enumerate(units)}
    for col in value_cols:
        unit = unit_map[col]
        fig.add_trace(go.Scatter(x=df[time_col], y=df[col], mode="lines", name=pretty_name(col), yaxis=axis_map[unit]))

    layout = {
        "xaxis": {"title": time_col},
        "yaxis": {"title": units[0] if units else "", "range": axis_ranges.get(units[0]) if units else None},
        "hovermode": "x unified",
        "legend": {"orientation": "h", "y": -0.25},
        "height": 650,
        "margin": {"l": 80, "r": 140, "t": 40, "b": 110},
    }
    for i, unit in enumerate(units[1:], start=2):
        layout[f"yaxis{i}"] = {
            "title": unit,
            "overlaying": "y",
            "side": "right",
            "anchor": "free",
            "position": max(0.0, 1.0 - 0.06 * (i - 2)),
            "range": axis_ranges.get(unit),
        }
    fig.update_layout(**layout)
    return fig


def calculate_summary_table(df):
    total = df.sum(numeric_only=True)
    delivered = total.get("delivered_volume_mwh", np.nan)
    nominated = total.get("nominated_volume_mwh", np.nan)
    volume_imbalance_mwh = delivered - nominated if pd.notna(delivered) and pd.notna(nominated) else np.nan

    summary = pd.DataFrame(
        index=["Volume", "Revenue", "Capture price", "Share wrt Total", "Share wrt EPEX"],
        columns=["Total", "EPEX", "Imbalance total", "Imbalance long", "Imbalance short"],
        dtype=float,
    )

    summary.loc["Volume", "Total"] = delivered
    summary.loc["Volume", "EPEX"] = nominated
    summary.loc["Volume", "Imbalance total"] = volume_imbalance_mwh
    summary.loc["Volume", "Imbalance long"] = total.get("volume_long_mwh", np.nan)
    summary.loc["Volume", "Imbalance short"] = total.get("volume_short_mwh", np.nan)

    summary.loc["Revenue", "Total"] = total.get("total_revenue", np.nan)
    summary.loc["Revenue", "EPEX"] = total.get("epex_revenue", np.nan)
    summary.loc["Revenue", "Imbalance total"] = total.get("imbalance_total_revenue", np.nan)
    summary.loc["Revenue", "Imbalance long"] = total.get("imbalance_long_revenue", np.nan)
    summary.loc["Revenue", "Imbalance short"] = total.get("imbalance_short_revenue", np.nan)

    summary.loc["Capture price", "Total"] = safe_div(summary.loc["Revenue", "Total"], summary.loc["Volume", "Total"])
    summary.loc["Capture price", "EPEX"] = safe_div(summary.loc["Revenue", "EPEX"], summary.loc["Volume", "EPEX"])
    summary.loc["Capture price", "Imbalance total"] = safe_div(summary.loc["Revenue", "Imbalance total"], abs(summary.loc["Volume", "Imbalance total"]))
    summary.loc["Capture price", "Imbalance long"] = safe_div(summary.loc["Revenue", "Imbalance long"], summary.loc["Volume", "Imbalance long"])
    summary.loc["Capture price", "Imbalance short"] = safe_div(summary.loc["Revenue", "Imbalance short"], summary.loc["Volume", "Imbalance short"])

    for col in summary.columns:
        summary.loc["Share wrt Total", col] = safe_div(summary.loc["Revenue", col], summary.loc["Revenue", "Total"])
        summary.loc["Share wrt EPEX", col] = safe_div(summary.loc["Revenue", col], summary.loc["Revenue", "EPEX"])
    return summary


def format_summary_table(summary):
    formatted = summary.astype("object").copy()
    for col in formatted.columns:
        formatted.loc["Volume", col] = format_value(summary.loc["Volume", col], "MWh", decimals=0)
        formatted.loc["Revenue", col] = format_value(summary.loc["Revenue", col], "€")
        formatted.loc["Capture price", col] = format_value(summary.loc["Capture price", col], "€/MWh")
        formatted.loc["Share wrt Total", col] = format_value(summary.loc["Share wrt Total", col], "%")
        formatted.loc["Share wrt EPEX", col] = format_value(summary.loc["Share wrt EPEX", col], "%")
    return formatted


def make_revenue_bridge(summary):
    epex = summary.loc["Revenue", "EPEX"]
    long = summary.loc["Revenue", "Imbalance long"]
    short = summary.loc["Revenue", "Imbalance short"]
    total = summary.loc["Revenue", "Total"]
    imbalance_total = summary.loc["Revenue", "Imbalance total"]

    components = []
    if pd.notna(epex):
        components.append(("EPEX", epex, "relative"))
    if pd.notna(long):
        components.append(("Long imbalance", long, "relative"))
    if pd.notna(short):
        components.append(("Short imbalance", short, "relative"))
    if pd.isna(long) and pd.isna(short) and pd.notna(imbalance_total):
        components.append(("Imbalance", imbalance_total, "relative"))
    if pd.notna(total):
        components.append(("Total", total, "total"))

    fig = go.Figure(go.Waterfall(
        name="Revenue bridge",
        orientation="v",
        measure=[m for _, _, m in components],
        x=[x for x, _, _ in components],
        y=[y for _, y, _ in components],
        text=[format_value(y, "€") for _, y, _ in components],
        textposition="outside",
        connector={"line": {"width": 1}},
    ))
    fig.update_layout(title="Revenue bridge", yaxis_title="€", height=450, margin={"l": 80, "r": 40, "t": 60, "b": 70})
    return fig


def add_diagnostic_columns(df):
    out = df.copy()
    if {"delivered_volume_mwh", "nominated_volume_mwh"}.issubset(out.columns):
        out["imbalance_volume_mwh_calc"] = out["delivered_volume_mwh"] - out["nominated_volume_mwh"]
        out["abs_imbalance_volume_mwh_calc"] = out["imbalance_volume_mwh_calc"].abs()
    if {"total_revenue", "epex_revenue"}.issubset(out.columns):
        out["revenue_vs_epex_calc"] = out["total_revenue"] - out["epex_revenue"]
    if {"total_revenue", "delivered_volume_mwh"}.issubset(out.columns):
        out["capture_total_calc"] = out["total_revenue"] / out["delivered_volume_mwh"].replace(0, np.nan)
    if {"epex_revenue", "nominated_volume_mwh"}.issubset(out.columns):
        out["capture_epex_calc"] = out["epex_revenue"] / out["nominated_volume_mwh"].replace(0, np.nan)
    if {"capture_total_calc", "capture_epex_calc"}.issubset(out.columns):
        out["capture_spread_vs_epex_calc"] = out["capture_total_calc"] - out["capture_epex_calc"]
    return out



def choose_default_volume_column(df):
    candidates = [
        "aap_volume_mwh",
        "AAP_volume_mwh",
        "delivered_volume_mwh",
        "nominated_volume_mwh",
    ]
    for col in candidates:
        if col in df.columns:
            return col
    mwh_cols = [c for c in df.columns if "mwh" in c.lower() and pd.api.types.is_numeric_dtype(df[c])]
    return mwh_cols[0] if mwh_cols else None


def add_greenchoice_benchmark(df, volume_col, epex_col, afslag_pct, afslag_min, gvo):
    out = df.copy()
    required = [volume_col, epex_col]
    if not volume_col or not epex_col or any(c not in out.columns for c in required):
        return out

    afslag_variable = out[epex_col] * afslag_pct
    # The floor means Greenchoice receives at least the minimum discount versus EPEX.
    # For negative EPEX prices, this still applies as a fixed €/MWh discount.
    out["greenchoice_afslag_eur_per_mwh"] = np.maximum(afslag_variable, afslag_min)
    out["greenchoice_net_price_eur_per_mwh"] = out[epex_col] - out["greenchoice_afslag_eur_per_mwh"] + gvo
    out["greenchoice_billable_price_eur_per_mwh"] = out["greenchoice_net_price_eur_per_mwh"].clip(lower=0)
    out["greenchoice_revenue"] = out[volume_col] * out["greenchoice_billable_price_eur_per_mwh"]
    if "total_revenue" in out.columns:
        out["revenue_vs_greenchoice_calc"] = out["total_revenue"] - out["greenchoice_revenue"]
    return out


def add_strike_price_diagnostic(df, epex_col, nomination_col, strike_price):
    out = df.copy()
    if not epex_col or not nomination_col or epex_col not in out.columns or nomination_col not in out.columns:
        return out
    below_strike = out[epex_col] < strike_price
    out["is_below_strike"] = below_strike
    out["strike_nomination_revenue"] = np.where(
        below_strike,
        out[nomination_col] * out[epex_col],
        0.0,
    )
    out["strike_volume_mwh"] = np.where(below_strike, out[nomination_col], 0.0)
    return out


def summarize_greenchoice(df):
    if "greenchoice_revenue" not in df.columns:
        return pd.DataFrame()
    total = df.sum(numeric_only=True)
    greenchoice = total.get("greenchoice_revenue", np.nan)
    actual = total.get("total_revenue", np.nan)
    volume = total.get("delivered_volume_mwh", np.nan)
    if pd.isna(volume) or volume == 0:
        volume = total.get("nominated_volume_mwh", np.nan)
    rows = [
        {"Metric": "Greenchoice benchmark revenue", "Value": greenchoice, "Unit": "€", "Interpretation": "AAP volume × max(EPEX - afslag + GvO, 0)."},
        {"Metric": "Greenchoice benchmark capture", "Value": safe_div(greenchoice, volume), "Unit": "€/MWh", "Interpretation": "Benchmark revenue divided by the selected AAP/delivered volume."},
    ]
    if pd.notna(actual):
        rows.append({"Metric": "Actual vs Greenchoice", "Value": actual - greenchoice, "Unit": "€", "Interpretation": "Positive means the actual result beat the Greenchoice benchmark."})
    return pd.DataFrame(rows)


def summarize_strike_price(df):
    if "strike_nomination_revenue" not in df.columns:
        return pd.DataFrame()
    below = df[df.get("is_below_strike", False)]
    total_revenue = df["strike_nomination_revenue"].sum()
    total_volume = df["strike_volume_mwh"].sum() if "strike_volume_mwh" in df.columns else np.nan
    rows = [
        {"Metric": "Periods below strike", "Value": len(below), "Unit": "count", "Interpretation": "Number of rows where EPEX was below the configured strike price."},
        {"Metric": "Nominated volume below strike", "Value": total_volume, "Unit": "MWh", "Interpretation": "Nominated volume exposed during below-strike periods."},
        {"Metric": "Nomination revenue below strike", "Value": total_revenue, "Unit": "€", "Interpretation": "Nominated volume × EPEX price during below-strike periods."},
    ]
    return pd.DataFrame(rows)


def format_generic_metric_table(table):
    if table.empty:
        return table
    out = table.copy()
    def fmt(row):
        if row["Unit"] == "count":
            return f"{int(row['Value']):,}" if pd.notna(row["Value"]) else "-"
        return format_value(row["Value"], row["Unit"])
    out["Value"] = out.apply(fmt, axis=1)
    return out.drop(columns=["Unit"])


def calculate_period_kpis(period_df):
    total = period_df.sum(numeric_only=True)
    delivered = total.get("delivered_volume_mwh", np.nan)
    total_revenue = total.get("total_revenue", np.nan)
    epex_revenue = total.get("epex_revenue", np.nan)
    greenchoice_revenue = total.get("greenchoice_revenue", np.nan)
    strike_revenue = total.get("strike_nomination_revenue", np.nan)
    imbalance_volume = total.get("imbalance_volume_mwh_calc", np.nan)

    return {
        "Delivered volume": format_value(delivered, "MWh", decimals=0),
        "Total revenue": format_value(total_revenue, "€"),
        "EPEX revenue": format_value(epex_revenue, "€"),
        "Greenchoice revenue": format_value(greenchoice_revenue, "€"),
        "Capture price": format_value(safe_div(total_revenue, delivered), "€/MWh"),
        "Net imbalance volume": format_value(imbalance_volume, "MWh", decimals=0),
        "Below-strike revenue": format_value(strike_revenue, "€"),
    }


def make_monthly_kpi_table(period_df, time_col):
    if period_df.empty:
        return pd.DataFrame()

    work = period_df.copy()
    work["month_period"] = work[time_col].dt.to_period("M")
    months = sorted(work["month_period"].dropna().unique())
    kpi_names = [
        "Delivered volume",
        "Total revenue",
        "EPEX revenue",
        "Greenchoice revenue",
        "Capture price",
        "Net imbalance volume",
        "Below-strike revenue",
    ]

    rows = {kpi: {} for kpi in kpi_names}
    for month in months:
        label = f"{calendar.month_abbr[month.month]} {month.year}"
        values = calculate_period_kpis(work[work["month_period"] == month])
        for kpi in kpi_names:
            rows[kpi][label] = values[kpi]

    ytd_values = calculate_period_kpis(work)
    for kpi in kpi_names:
        rows[kpi]["YTD total"] = ytd_values[kpi]

    return pd.DataFrame.from_dict(rows, orient="index").reset_index(names="KPI")


def make_monthly_numeric_table(period_df, time_col):
    if period_df.empty:
        return pd.DataFrame()
    work = period_df.copy()
    work["Month"] = work[time_col].dt.to_period("M").astype(str)
    grouped = work.groupby("Month").sum(numeric_only=True)
    rows = []
    for month, total in grouped.iterrows():
        delivered = total.get("delivered_volume_mwh", np.nan)
        total_revenue = total.get("total_revenue", np.nan)
        epex_revenue = total.get("epex_revenue", np.nan)
        greenchoice_revenue = total.get("greenchoice_revenue", np.nan)
        rows.append({
            "Month": month,
            "Delivered volume MWh": delivered,
            "Total revenue EUR": total_revenue,
            "EPEX revenue EUR": epex_revenue,
            "Greenchoice revenue EUR": greenchoice_revenue,
            "Capture price EUR/MWh": safe_div(total_revenue, delivered),
            "Net imbalance volume MWh": total.get("imbalance_volume_mwh_calc", np.nan),
            "Below-strike revenue EUR": total.get("strike_nomination_revenue", np.nan),
        })

    ytd_total = work.sum(numeric_only=True)
    delivered = ytd_total.get("delivered_volume_mwh", np.nan)
    total_revenue = ytd_total.get("total_revenue", np.nan)
    rows.append({
        "Month": "YTD total",
        "Delivered volume MWh": delivered,
        "Total revenue EUR": total_revenue,
        "EPEX revenue EUR": ytd_total.get("epex_revenue", np.nan),
        "Greenchoice revenue EUR": ytd_total.get("greenchoice_revenue", np.nan),
        "Capture price EUR/MWh": safe_div(total_revenue, delivered),
        "Net imbalance volume MWh": ytd_total.get("imbalance_volume_mwh_calc", np.nan),
        "Below-strike revenue EUR": ytd_total.get("strike_nomination_revenue", np.nan),
    })
    return pd.DataFrame(rows)


def make_monthly_chart_source(period_df, time_col):
    numeric = make_monthly_numeric_table(period_df, time_col)
    if numeric.empty:
        return numeric
    return numeric[numeric["Month"] != "YTD total"].copy()


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


def build_anomaly_table(df, time_col, metric, n=10, largest=True, title="Anomaly"):
    if metric not in df.columns:
        return pd.DataFrame()

    context_cols = existing([
        "delivered_volume_mwh",
        "nominated_volume_mwh",
        "imbalance_volume_mwh_calc",
        "abs_imbalance_volume_mwh_calc",
        "epex_eur_per_mwh",
        "imbalance_long_eur_per_mwh",
        "imbalance_short_eur_per_mwh",
        "total_revenue",
        "epex_revenue",
        "imbalance_total_revenue",
        "greenchoice_revenue",
        "revenue_vs_greenchoice_calc",
        "strike_nomination_revenue",
    ], df)
    cols = [time_col, metric] + [c for c in context_cols if c != metric]
    raw = df[cols].dropna(subset=[metric]).sort_values(metric, ascending=not largest).head(n).copy()
    if raw.empty:
        return raw

    def explain(row):
        parts = []
        metric_value = row.get(metric, np.nan)
        if metric == "revenue_vs_epex_calc":
            direction = "above" if metric_value >= 0 else "below"
            parts.append(f"Total revenue is {format_value(abs(metric_value), '€')} {direction} EPEX revenue.")
            if "imbalance_volume_mwh_calc" in row:
                parts.append(f"Net imbalance: {format_value(row['imbalance_volume_mwh_calc'], 'MWh')}.")
        elif metric == "revenue_vs_greenchoice_calc":
            direction = "above" if metric_value >= 0 else "below"
            parts.append(f"Actual revenue is {format_value(abs(metric_value), '€')} {direction} the Greenchoice benchmark.")
            if "greenchoice_revenue" in row:
                parts.append(f"Benchmark revenue: {format_value(row['greenchoice_revenue'], '€')}.")
        elif metric == "abs_imbalance_volume_mwh_calc":
            parts.append(f"Large imbalance exposure of {format_value(metric_value, 'MWh')}.")
            if "imbalance_volume_mwh_calc" in row:
                direction = "long" if row["imbalance_volume_mwh_calc"] >= 0 else "short"
                parts.append(f"Direction: {direction}.")
        elif metric == "capture_spread_vs_epex_calc":
            direction = "higher" if metric_value >= 0 else "lower"
            parts.append(f"Total capture is {format_value(abs(metric_value), '€/MWh')} {direction} than EPEX capture.")
        elif metric == "strike_nomination_revenue":
            parts.append(f"Below-strike nomination revenue: {format_value(metric_value, '€')}.")
            if "nominated_volume_mwh" in row and "epex_eur_per_mwh" in row:
                parts.append(f"Nominated {format_value(row['nominated_volume_mwh'], 'MWh')} at EPEX {format_value(row['epex_eur_per_mwh'], '€/MWh')}.")
        else:
            parts.append(f"{pretty_name(metric)} equals {format_value(metric_value, infer_unit(metric))}.")
        return " ".join(parts)

    raw.insert(1, "Where is the anomaly?", raw.apply(explain, axis=1))
    raw.insert(2, "Impact", raw[metric].apply(lambda v: format_value(v, infer_unit(metric))))
    display_cols = [time_col, "Where is the anomaly?", "Impact"] + [c for c in raw.columns if c not in [time_col, "Where is the anomaly?", "Impact", metric]]
    out = raw[display_cols].rename(columns={c: pretty_name(c) for c in display_cols if c not in [time_col, "Where is the anomaly?", "Impact"]})
    return out

def make_variance_table(df):
    rows = []
    total = df.sum(numeric_only=True)
    if {"total_revenue", "epex_revenue"}.issubset(df.columns):
        total_rev = total.get("total_revenue", np.nan)
        epex_rev = total.get("epex_revenue", np.nan)
        rows.append({"Metric": "Revenue vs EPEX", "Value": total_rev - epex_rev, "Unit": "€", "Interpretation": "Positive means total revenue exceeded nominated EPEX revenue."})
    if {"delivered_volume_mwh", "nominated_volume_mwh"}.issubset(df.columns):
        delivered = total.get("delivered_volume_mwh", np.nan)
        nominated = total.get("nominated_volume_mwh", np.nan)
        rows.append({"Metric": "Delivered vs nominated volume", "Value": delivered - nominated, "Unit": "MWh", "Interpretation": "Positive means delivered volume exceeded nomination."})
    if {"capture_total_calc", "capture_epex_calc"}.issubset(df.columns):
        total_capture = safe_div(total.get("total_revenue", np.nan), total.get("delivered_volume_mwh", np.nan))
        epex_capture = safe_div(total.get("epex_revenue", np.nan), total.get("nominated_volume_mwh", np.nan))
        rows.append({"Metric": "Capture spread vs EPEX", "Value": total_capture - epex_capture, "Unit": "€/MWh", "Interpretation": "Positive means total capture beat EPEX capture."})
    return pd.DataFrame(rows)


def format_variance_table(table):
    if table.empty:
        return table
    out = table.copy()
    out["Value"] = [format_value(v, u) for v, u in zip(out["Value"], out["Unit"])]
    return out.drop(columns=["Unit"])


def top_periods(df, time_col, metric, n=10, largest=True):
    if metric not in df.columns:
        return pd.DataFrame()
    cols = [time_col, metric]
    extra_cols = existing(["delivered_volume_mwh", "nominated_volume_mwh", "epex_eur_per_mwh", "imbalance_long_eur_per_mwh", "imbalance_short_eur_per_mwh"], df)
    cols += [c for c in extra_cols if c not in cols]
    result = df[cols].dropna(subset=[metric]).sort_values(metric, ascending=not largest).head(n)
    return result.rename(columns={c: pretty_name(c) for c in result.columns})


def make_data_quality_table(df, time_col):
    checks = []
    checks.append({"Check": "Rows loaded", "Result": len(df), "Status": "OK" if len(df) > 0 else "Issue"})
    checks.append({"Check": "Duplicate timestamps", "Result": int(df[time_col].duplicated().sum()), "Status": "Issue" if df[time_col].duplicated().any() else "OK"})
    numeric_missing = int(df.select_dtypes(include=[np.number]).isna().sum().sum())
    checks.append({"Check": "Missing numeric values", "Result": numeric_missing, "Status": "Review" if numeric_missing else "OK"})
    if len(df) > 1:
        median_step = df[time_col].sort_values().diff().median()
        checks.append({"Check": "Median timestamp step", "Result": str(median_step), "Status": "OK"})
    if {"total_revenue", "epex_revenue", "imbalance_total_revenue"}.issubset(df.columns):
        diff = (df["total_revenue"] - df["epex_revenue"] - df["imbalance_total_revenue"]).abs().sum()
        checks.append({"Check": "Revenue identity residual", "Result": f"€{diff:,.2f}", "Status": "Review" if diff > 1e-6 else "OK"})

    # Streamlit serializes dataframes through Arrow. Keep display columns
    # consistently typed to avoid warnings/errors when Result mixes ints,
    # strings, timedeltas, and currency-formatted values.
    q = pd.DataFrame(checks)
    q["Check"] = q["Check"].astype(str)
    q["Result"] = q["Result"].astype(str)
    q["Status"] = q["Status"].astype(str)
    return q


@st.cache_resource
def get_container_client():
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        try:
            conn_str = st.secrets["AZURE_STORAGE_CONNECTION_STRING"]
        except Exception:
            conn_str = None
    if not conn_str:
        st.error("AZURE_STORAGE_CONNECTION_STRING is not configured.")
        st.stop()
    service = BlobServiceClient.from_connection_string(conn_str)
    return service.get_container_client(CONTAINER_NAME)


@st.cache_data(ttl=300)
def list_csv_blobs(prefix):
    container = get_container_client()
    return sorted(blob.name for blob in container.list_blobs(name_starts_with=prefix) if blob.name.endswith(".csv"))


@st.cache_data(ttl=300)
def read_blob_csv(blob_name):
    container = get_container_client()
    blob_bytes = container.download_blob(blob_name).readall()
    return pd.read_csv(BytesIO(blob_bytes))


export_files = list_csv_blobs("exports/")
if not export_files:
    st.error("No YTD export files found in Blob Storage under exports/")
    st.stop()
selected_blob = export_files[-1]

raw_df = read_blob_csv(selected_blob)
st.caption(f"YTD dataset: `{selected_blob}`")

TIMESTAMP_COLUMNS = ["timestamp_Ams", "timestamp_UTC"]
GREENCHOICE_VOLUME_COL = "delivered_volume_mwh"
EPEX_PRICE_COL = "epex_eur_per_mwh"
NOMINATION_VOLUME_COL = "nominated_volume_mwh"

timestamp_options = [c for c in TIMESTAMP_COLUMNS if c in raw_df.columns]
if not timestamp_options:
    st.error("The YTD export must contain either `timestamp_Ams` or `timestamp_UTC`.")
    st.stop()

def month_bounds(year, month, min_date, max_date):
    start = pd.Timestamp(year=year, month=month, day=1).date()
    end = pd.Timestamp(year=year, month=month, day=calendar.monthrange(year, month)[1]).date()
    return max(start, min_date), min(end, max_date)


def last_full_month_bounds(reference_date, min_date, max_date):
    first_of_reference_month = pd.Timestamp(reference_date).replace(day=1)
    last_full_month_end = (first_of_reference_month - pd.Timedelta(days=1)).date()
    last_full_month_start = last_full_month_end.replace(day=1)
    return max(last_full_month_start, min_date), min(last_full_month_end, max_date)

with st.sidebar:
    st.header("Controls")
    default_time_index = timestamp_options.index("timestamp_Ams") if "timestamp_Ams" in timestamp_options else 0
    time_col = st.selectbox("Timestamp", timestamp_options, index=default_time_index, key="v13_timestamp_column_selector")

raw_df[time_col] = pd.to_datetime(raw_df[time_col], errors="coerce")
df = raw_df.dropna(subset=[time_col]).sort_values(time_col)
ytd_source_df = df.copy()

min_date = df[time_col].min().date()
max_date = df[time_col].max().date()
available_months = sorted(df[time_col].dt.to_period("M").dropna().unique())
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

    # Use a separate date-input key for each quick-period choice. This lets the
    # calendar visibly update when a month is selected without writing to the
    # same widget key through Session State, which avoids Streamlit's warning.
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

if len(date_range) == 2:
    start_date, end_date = date_range
    df = df[(df[time_col].dt.date >= start_date) & (df[time_col].dt.date <= end_date)]

# Diagnostics for the selected period.
df = add_diagnostic_columns(df)
df = add_greenchoice_benchmark(df, GREENCHOICE_VOLUME_COL, EPEX_PRICE_COL, afslag_pct, afslag_min, gvo)
df = add_strike_price_diagnostic(df, EPEX_PRICE_COL, NOMINATION_VOLUME_COL, strike_price)

# Diagnostics for the full YTD export, used by the monthly/YTD overview.
ytd_analysis_df = add_diagnostic_columns(ytd_source_df)
ytd_analysis_df = add_greenchoice_benchmark(ytd_analysis_df, GREENCHOICE_VOLUME_COL, EPEX_PRICE_COL, afslag_pct, afslag_min, gvo)
ytd_analysis_df = add_strike_price_diagnostic(ytd_analysis_df, EPEX_PRICE_COL, NOMINATION_VOLUME_COL, strike_price)

numeric_cols = [col for col in df.columns if col != time_col and pd.api.types.is_numeric_dtype(df[col])]
summary_table = calculate_summary_table(df)



def make_status_label(value, positive_good=True):
    if pd.isna(value):
        return "No data"
    good = value >= 0 if positive_good else value <= 0
    return "Positive" if good else "Warning"


def make_delta_help(value, positive_text, negative_text):
    if pd.isna(value):
        return "Not enough data to calculate this diagnostic."
    return positive_text if value >= 0 else negative_text


def format_period_label(df, time_col):
    if df.empty:
        return "-"
    start = df[time_col].min().strftime("%Y-%m-%d %H:%M")
    end = df[time_col].max().strftime("%Y-%m-%d %H:%M")
    return f"{start} to {end}"


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
            # Plotly line is a graph object, not always dict-convertible.
            # update() preserves existing line settings and only sets color.
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


def make_greenchoice_bridge(df):
    total = df.sum(numeric_only=True)
    actual = total.get("total_revenue", np.nan)
    benchmark = total.get("greenchoice_revenue", np.nan)
    delta = total.get("revenue_vs_greenchoice_calc", np.nan)
    if pd.isna(benchmark) or pd.isna(actual):
        return go.Figure()
    fig = go.Figure(go.Waterfall(
        name="Actual vs Greenchoice",
        measure=["relative", "relative", "total"],
        x=["Greenchoice benchmark", "Actual delta", "Actual revenue"],
        y=[benchmark, delta, actual],
        text=[format_value(benchmark, "€"), format_value(delta, "€"), format_value(actual, "€")],
        textposition="outside",
        connector={"line": {"width": 1}},
    ))
    fig.update_yaxes(title="€")
    return style_plotly(fig, title="Actual revenue vs Greenchoice benchmark", height=430)


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


def render_executive_narrative(df, summary_table, variance_table, gc_summary, strike_summary):
    total_revenue = summary_table.loc["Revenue", "Total"] if "Total" in summary_table.columns else np.nan
    rev_vs_epex = variance_table.loc[variance_table["Metric"] == "Revenue vs EPEX", "Value"]
    rev_vs_epex = rev_vs_epex.iloc[0] if len(rev_vs_epex) else np.nan
    rev_vs_gc = df["revenue_vs_greenchoice_calc"].sum() if "revenue_vs_greenchoice_calc" in df.columns else np.nan
    strike_rev = df["strike_nomination_revenue"].sum() if "strike_nomination_revenue" in df.columns else np.nan
    below_count = int(df["is_below_strike"].sum()) if "is_below_strike" in df.columns else 0

    bullets = []
    if pd.notna(total_revenue):
        bullets.append(f"Total revenue for the selected period is **{format_value(total_revenue, '€')}**.")
    if pd.notna(rev_vs_epex):
        direction = "above" if rev_vs_epex >= 0 else "below"
        bullets.append(f"Actual revenue is **{format_value(abs(rev_vs_epex), '€')} {direction} EPEX nomination revenue**.")
    if pd.notna(rev_vs_gc):
        direction = "above" if rev_vs_gc >= 0 else "below"
        bullets.append(f"Actual revenue is **{format_value(abs(rev_vs_gc), '€')} {direction} the Greenchoice benchmark**.")
    if pd.notna(strike_rev):
        bullets.append(f"There are **{below_count:,} below-strike periods**, with nomination revenue of **{format_value(strike_rev, '€')}** during those periods.")
    if bullets:
        st.markdown("\n".join(f"- {b}" for b in bullets))
    else:
        st.info("Not enough recognized columns to generate an executive summary.")

st.header("Dashboard")

# Recompute diagnostics used across tabs.
variance_table = make_variance_table(df)
gc_summary = summarize_greenchoice(df)
strike_summary = summarize_strike_price(df)

# Core totals for KPI cards.
total_revenue = summary_table.loc["Revenue", "Total"]
total_capture = summary_table.loc["Capture price", "Total"]
delivered_volume = summary_table.loc["Volume", "Total"]
nominated_volume = summary_table.loc["Volume", "EPEX"]
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
    render_executive_narrative(df, summary_table, variance_table, gc_summary, strike_summary)

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

    anomaly_specs = [
        ("Revenue upside", "revenue_vs_epex_calc", True, "anomaly_revenue_upside.csv", "Periods where actual revenue most exceeded EPEX nomination revenue."),
        ("Revenue downside", "revenue_vs_epex_calc", False, "anomaly_revenue_downside.csv", "Periods where actual revenue most underperformed EPEX nomination revenue."),
        ("Greenchoice gap", "revenue_vs_greenchoice_calc", False, "anomaly_greenchoice_gap.csv", "Periods where actual revenue most underperformed the Greenchoice benchmark."),
        ("Largest imbalance", "abs_imbalance_volume_mwh_calc", True, "anomaly_largest_imbalance.csv", "Periods with the largest absolute delivered-versus-nominated imbalance."),
        ("Capture spread", "capture_spread_vs_epex_calc", False, "anomaly_capture_spread.csv", "Periods with the weakest total capture versus EPEX capture."),
        ("Below strike", "strike_nomination_revenue", False, "anomaly_below_strike.csv", "Below-strike periods with the most negative nomination revenue."),
    ]
    tabs = st.tabs([x[0] for x in anomaly_specs])
    for tab, (label, metric, largest, file_name, explanation) in zip(tabs, anomaly_specs):
        with tab:
            st.markdown(f"**Focus:** {explanation}")
            source_df = df[df["is_below_strike"]] if label == "Below strike" and "is_below_strike" in df.columns else df
            table = build_anomaly_table(source_df, time_col, metric, anomaly_n, largest=largest)
            st.dataframe(table, width="stretch", hide_index=True)
            make_anomaly_download(table, f"Download {label.lower()} table", file_name)

with timeseries_tab:
    st.subheader("Styled timeseries explorer")
    chart_groups = {
        "Volumes": ["nominated_volume_mwh", "delivered_volume_mwh", "imbalance_volume_mwh_calc"],
        "Revenue components": ["total_revenue", "epex_revenue", "imbalance_total_revenue", "greenchoice_revenue"],
        "Revenue deltas": ["revenue_vs_epex_calc", "revenue_vs_greenchoice_calc", "strike_nomination_revenue"],
        "Prices and capture": ["epex_eur_per_mwh", "greenchoice_net_price_eur_per_mwh", "greenchoice_billable_price_eur_per_mwh", "capture_total_calc", "capture_epex_calc"],
        "Imbalance prices": ["imbalance_long_eur_per_mwh", "imbalance_short_eur_per_mwh"],
    }
    available_groups = {title: [c for c in cols if c in numeric_cols] for title, cols in chart_groups.items()}
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
    q = make_data_quality_table(df, time_col)
    st.dataframe(q, width="stretch", hide_index=True)

    st.subheader("Selected assumptions")
    assumptions = pd.DataFrame([
        {"Setting": "Greenchoice volume column", "Value": GREENCHOICE_VOLUME_COL},
        {"Setting": "EPEX price column", "Value": EPEX_PRICE_COL},
        {"Setting": "Strike nomination volume column", "Value": NOMINATION_VOLUME_COL},
        {"Setting": "Greenchoice afslag", "Value": f"{afslag_pct:.1%}"},
        {"Setting": "Greenchoice afslag floor", "Value": format_value(afslag_min, "€/MWh")},
        {"Setting": "GvO", "Value": format_value(gvo, "€/MWh")},
        {"Setting": "Strike price", "Value": format_value(strike_price, "€/MWh")},
    ])
    st.dataframe(assumptions, width="stretch", hide_index=True)

    st.subheader("Recognized columns")
    recognized = pd.DataFrame([
        {"Column": c, "Label": pretty_name(c), "Unit": infer_unit(c), "Aggregation": agg_for_col(c)}
        for c in numeric_cols
    ])
    st.dataframe(recognized, width="stretch", hide_index=True)
