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


st.set_page_config(page_title="Timeseries Viewer v1.2", layout="wide")
st.title("Timeseries Viewer v1.2")
st.caption("Decision-support layer for EPEX, imbalance, revenue, and capture diagnostics.")


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
    return pd.DataFrame(checks)


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


selected_blob = None
with st.sidebar:
    st.header("Data source")
    dataset_type = st.radio("Choose dataset", ["Monthly file", "YTD export"], key="dataset_type")

    if dataset_type == "Monthly file":
        monthly_blob_names = list_csv_blobs("monthly/")
        years = sorted({name.split("/")[1] for name in monthly_blob_names if len(name.split("/")) >= 3})
        if not years:
            st.error("No monthly files found in Blob Storage under monthly/YYYY/")
            st.stop()
        selected_year = st.selectbox("Year", years, key="selected_year")
        monthly_files = list_csv_blobs(f"monthly/{selected_year}/")
        selected_blob = st.selectbox("Month", monthly_files, format_func=lambda x: x.split("/")[-1].replace(".csv", ""), key="selected_month_blob")
    else:
        export_files = list_csv_blobs("exports/")
        if not export_files:
            st.error("No YTD export files found in Blob Storage under exports/")
            st.stop()
        selected_blob = st.selectbox("YTD export", export_files, format_func=lambda x: x.split("/")[-1].replace(".csv", ""), key="selected_ytd_blob")

if not selected_blob:
    st.info("Choose a dataset to start.")
    st.stop()

raw_df = read_blob_csv(selected_blob)
st.caption(f"Loaded from Azure Blob Storage: `{selected_blob}`")

time_candidates = [c for c in raw_df.columns if "timestamp" in c.lower() or "date" in c.lower() or "time" in c.lower()]
default_time_col = "timestamp_Ams" if "timestamp_Ams" in raw_df.columns else (time_candidates[0] if time_candidates else raw_df.columns[0])

with st.sidebar:
    st.header("Controls")
    time_col = st.selectbox("Timestamp column", raw_df.columns, index=list(raw_df.columns).index(default_time_col), key="timestamp_column_selector")

raw_df[time_col] = pd.to_datetime(raw_df[time_col], errors="coerce")
df = raw_df.dropna(subset=[time_col]).sort_values(time_col)

min_date = df[time_col].min().date()
max_date = df[time_col].max().date()

with st.sidebar:
    date_range = st.date_input("Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date, key="date_range")
    rule = st.selectbox(
        "Resampling frequency",
        ["Original", "15min", "h", "D", "W", "ME", "YE"],
        format_func=lambda x: {"Original": "Original", "15min": "15 minutes", "h": "Hourly", "D": "Daily", "W": "Weekly", "ME": "Monthly", "YE": "Yearly"}[x],
        key="resampling_frequency",
    )
    anomaly_n = st.slider("Rows in anomaly tables", min_value=5, max_value=30, value=10, step=5)

    st.header("Benchmark settings")
    numeric_raw_cols = [col for col in raw_df.columns if pd.api.types.is_numeric_dtype(raw_df[col])]
    default_aap_col = choose_default_volume_column(raw_df)
    default_epex_col = "epex_eur_per_mwh" if "epex_eur_per_mwh" in raw_df.columns else (numeric_raw_cols[0] if numeric_raw_cols else None)
    default_nomination_col = "nominated_volume_mwh" if "nominated_volume_mwh" in raw_df.columns else default_aap_col

    aap_volume_col = st.selectbox(
        "AAP volume column",
        numeric_raw_cols,
        index=numeric_raw_cols.index(default_aap_col) if default_aap_col in numeric_raw_cols else 0,
        key="aap_volume_col",
        help="Used for the Greenchoice benchmark. If there is no explicit AAP column, delivered volume is the default fallback.",
    ) if numeric_raw_cols else None
    epex_price_col = st.selectbox(
        "EPEX price column",
        numeric_raw_cols,
        index=numeric_raw_cols.index(default_epex_col) if default_epex_col in numeric_raw_cols else 0,
        key="epex_price_col",
    ) if numeric_raw_cols else None
    nomination_volume_col = st.selectbox(
        "Nomination volume column",
        numeric_raw_cols,
        index=numeric_raw_cols.index(default_nomination_col) if default_nomination_col in numeric_raw_cols else 0,
        key="nomination_volume_col",
        help="Used for strike-price exposure.",
    ) if numeric_raw_cols else None

    afslag_pct = st.number_input("Greenchoice afslag (%)", min_value=0.0, max_value=100.0, value=11.0, step=0.5, key="gc_afslag_pct") / 100.0
    afslag_min = st.number_input("Greenchoice afslag floor (€/MWh)", value=8.0, step=0.5, key="gc_afslag_min")
    gvo = st.number_input("GvO value (€/MWh)", value=1.80, step=0.10, key="gc_gvo")
    strike_price = st.number_input("Strike price for negative nomination revenue (€/MWh)", value=0.0, step=1.0, key="strike_price")

if len(date_range) == 2:
    start_date, end_date = date_range
    df = df[(df[time_col].dt.date >= start_date) & (df[time_col].dt.date <= end_date)]

df = add_diagnostic_columns(df)
df = add_greenchoice_benchmark(df, aap_volume_col, epex_price_col, afslag_pct, afslag_min, gvo)
df = add_strike_price_diagnostic(df, epex_price_col, nomination_volume_col, strike_price)
numeric_cols = [col for col in df.columns if col != time_col and pd.api.types.is_numeric_dtype(df[col])]
summary_table = calculate_summary_table(df)

st.header("Data context")
ctx1, ctx2, ctx3, ctx4 = st.columns(4)
ctx1.metric("Rows", f"{len(df):,}")
ctx2.metric("Columns", f"{len(df.columns):,}")
ctx3.metric("Start", df[time_col].min().strftime("%Y-%m-%d %H:%M") if len(df) else "-")
ctx4.metric("End", df[time_col].max().strftime("%Y-%m-%d %H:%M") if len(df) else "-")

with st.expander("Data quality checks", expanded=False):
    st.dataframe(make_data_quality_table(df, time_col), use_container_width=True, hide_index=True)

st.header("Executive summary")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Delivered volume", format_value(summary_table.loc["Volume", "Total"], "MWh", decimals=0))
c2.metric("Nominated volume", format_value(summary_table.loc["Volume", "EPEX"], "MWh", decimals=0))
c3.metric("Total revenue", format_value(summary_table.loc["Revenue", "Total"], "€"))
c4.metric("Total capture", format_value(summary_table.loc["Capture price", "Total"], "€/MWh"))

variance_table = make_variance_table(df)
if not variance_table.empty:
    v1, v2, v3 = st.columns(3)
    for i, row in variance_table.iterrows():
        with [v1, v2, v3][i % 3]:
            st.metric(row["Metric"], format_value(row["Value"], row["Unit"]))

st.header("Revenue bridge and benchmarks")
left, right = st.columns([1.35, 1])
with left:
    st.plotly_chart(make_revenue_bridge(summary_table), use_container_width=True)
with right:
    st.subheader("Variance diagnostics")
    st.dataframe(format_variance_table(variance_table), use_container_width=True, hide_index=True)
    st.caption("EPEX/nominated revenue is used as the reference where available.")

st.subheader("Greenchoice benchmark")
gc_summary = summarize_greenchoice(df)
gc1, gc2, gc3 = st.columns(3)
if not gc_summary.empty:
    for i, row in gc_summary.iterrows():
        with [gc1, gc2, gc3][i % 3]:
            st.metric(row["Metric"], format_value(row["Value"], row["Unit"]) if row["Unit"] != "count" else f"{int(row['Value']):,}")
    with st.expander("Greenchoice benchmark formula", expanded=False):
        st.markdown(
            "Benchmark revenue = AAP volume × max(EPEX - max(EPEX × afslag %, afslag floor) + GvO, 0). "
            "The final max(..., 0) means a negative net price creates zero revenue rather than a loss."
        )
        st.dataframe(format_generic_metric_table(gc_summary), use_container_width=True, hide_index=True)
else:
    st.info("Greenchoice benchmark unavailable because the selected volume or EPEX price column is missing.")

st.subheader("Strike-price nomination exposure")
strike_summary = summarize_strike_price(df)
if not strike_summary.empty:
    s1, s2, s3 = st.columns(3)
    for i, row in strike_summary.iterrows():
        with [s1, s2, s3][i % 3]:
            st.metric(row["Metric"], format_value(row["Value"], row["Unit"]) if row["Unit"] != "count" else f"{int(row['Value']):,}")
    with st.expander("Strike-price explanation", expanded=False):
        st.markdown(
            "This isolates nominated volume during periods where EPEX is below the configured strike price. "
            "Default strike is 0 €/MWh, so the diagnostic highlights negative EPEX nomination revenue."
        )
        st.dataframe(format_generic_metric_table(strike_summary), use_container_width=True, hide_index=True)
else:
    st.info("Strike-price diagnostic unavailable because the selected nomination or EPEX price column is missing.")

st.header("Breakdown")
st.dataframe(format_summary_table(summary_table), use_container_width=True)
st.caption("Note: imbalance-total capture price uses absolute net imbalance volume in the denominator, so interpret it as €/MWh of absolute imbalance exposure rather than directional price.")

st.header("Anomaly finder")
st.caption("Each row now starts with the suspected anomaly and the estimated impact, followed by the context columns needed to investigate it.")
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Revenue upside",
    "Revenue downside",
    "Greenchoice gap",
    "Largest imbalance",
    "Capture spread",
    "Below strike",
])
with tab1:
    st.dataframe(build_anomaly_table(df, time_col, "revenue_vs_epex_calc", anomaly_n, largest=True), use_container_width=True, hide_index=True)
with tab2:
    st.dataframe(build_anomaly_table(df, time_col, "revenue_vs_epex_calc", anomaly_n, largest=False), use_container_width=True, hide_index=True)
with tab3:
    st.dataframe(build_anomaly_table(df, time_col, "revenue_vs_greenchoice_calc", anomaly_n, largest=False), use_container_width=True, hide_index=True)
with tab4:
    st.dataframe(build_anomaly_table(df, time_col, "abs_imbalance_volume_mwh_calc", anomaly_n, largest=True), use_container_width=True, hide_index=True)
with tab5:
    st.dataframe(build_anomaly_table(df, time_col, "capture_spread_vs_epex_calc", anomaly_n, largest=False), use_container_width=True, hide_index=True)
with tab6:
    below_strike_df = df[df["is_below_strike"]] if "is_below_strike" in df.columns else df.iloc[0:0]
    st.dataframe(build_anomaly_table(below_strike_df, time_col, "strike_nomination_revenue", anomaly_n, largest=False), use_container_width=True, hide_index=True)

chart_groups = {
    "1) Volumes and EPEX price": ["nominated_volume_mwh", "delivered_volume_mwh", "epex_eur_per_mwh"],
    "2) Revenue components": ["total_revenue", "epex_revenue", "imbalance_total_revenue", "imbalance_short_revenue", "imbalance_long_revenue", "revenue_vs_epex_calc"],
    "3) Imbalance prices": ["imbalance_total_revenue", "imbalance_long_eur_per_mwh", "imbalance_short_eur_per_mwh"],
    "4) Capture diagnostics": ["capture_total_calc", "capture_epex_calc", "capture_spread_vs_epex_calc"],
    "5) Greenchoice benchmark": ["greenchoice_revenue", "revenue_vs_greenchoice_calc", "greenchoice_net_price_eur_per_mwh", "greenchoice_billable_price_eur_per_mwh"],
    "6) Strike-price exposure": ["strike_nomination_revenue", "strike_volume_mwh"],
}

available_groups = {title: [c for c in cols if c in numeric_cols] for title, cols in chart_groups.items()}
all_chart_cols = sorted(set(c for cols in available_groups.values() for c in cols))

if all_chart_cols:
    unit_map = {col: infer_unit(col) for col in all_chart_cols}
    # Override calculated diagnostic units.
    unit_map.update({
        "revenue_vs_epex_calc": "€",
        "imbalance_volume_mwh_calc": "MWh",
        "abs_imbalance_volume_mwh_calc": "MWh",
        "capture_total_calc": "€/MWh",
        "capture_epex_calc": "€/MWh",
        "capture_spread_vs_epex_calc": "€/MWh",
        "greenchoice_afslag_eur_per_mwh": "€/MWh",
        "greenchoice_net_price_eur_per_mwh": "€/MWh",
        "greenchoice_billable_price_eur_per_mwh": "€/MWh",
        "greenchoice_revenue": "€",
        "revenue_vs_greenchoice_calc": "€",
        "strike_nomination_revenue": "€",
        "strike_volume_mwh": "MWh",
    })
    plot_df = resample_df(df, time_col, all_chart_cols, rule)

    st.header("Timeseries explorer")
    for title, cols in available_groups.items():
        if cols:
            st.subheader(title)
            render_aggregate_metrics(df, cols, unit_map)
            units = []
            for col in cols:
                unit = unit_map[col]
                if unit not in units:
                    units.append(unit)
            axis_ranges = axis_range_inputs(title, units, plot_df, cols, unit_map)
            fig = make_multi_axis_plot(plot_df, time_col, cols, unit_map, axis_ranges)
            st.plotly_chart(fig, use_container_width=True)
else:
    st.info("None of the predefined chart columns were found.")
