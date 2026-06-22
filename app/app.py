# -*- coding: utf-8 -*-
"""
Created on Tue Jun  2 12:20:35 2026

@author: VictorVerbist
"""

# app.py
import re
import os
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from azure.storage.blob import BlobServiceClient
from io import BytesIO



CONTAINER_NAME = "rw5data-turbine-edmij-entsoe"


st.set_page_config(page_title="Timeseries Viewer", layout="wide")
st.title("Timeseries Viewer")


def infer_unit(col):
    c = col.lower()

    if "eur_per_mwh" in c or "price" in c:
        return "€/MWh"
    if "revenue" in c:
        return "€"
    if "mwh" in c or "volume" in c:
        return "MWh"
    if "capture" in c:
        return "€/MWh"
    if "performance" in c:
        return "ratio"
    if "share" in c:
        return "%"

    match = re.search(r"\[(.*?)\]|\((.*?)\)", col)
    if match:
        return match.group(1) or match.group(2)

    return "Other"


def agg_for_col(col):
    c = col.lower()

    if "eur_per_mwh" in c or "capture" in c or "performance" in c or "share" in c:
        return "mean"
    if "mwh" in c or "volume" in c or "revenue" in c:
        return "sum"

    return "mean"


def format_value(value, unit):
    if pd.isna(value):
        return "-"

    if unit == "€":
        return f"€{value:,.0f}"
    if unit == "€/MWh":
        return f"{value:,.2f} €/MWh"
    if unit == "MWh":
        return f"{value:,.2f} MWh"
    if unit == "%":
        return f"{value:,.2%}" if abs(value) <= 1 else f"{value:,.2f}%"
    if unit == "ratio":
        return f"{value:,.3f}"

    return f"{value:,.2f}"


def resample_df(df, time_col, value_cols, rule):
    if rule == "Original":
        return df[[time_col] + value_cols].copy()

    temp = df[[time_col] + value_cols].copy()
    temp = temp.set_index(time_col)

    agg_map = {col: agg_for_col(col) for col in value_cols}
    temp = temp.resample(rule).agg(agg_map)

    return temp.reset_index()


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
            st.metric(col, values[col])


def axis_range_inputs(chart_title, units, df, value_cols, unit_map):
    ranges = {}

    with st.expander("Y-axis ranges", expanded=False):
        axis_cols = st.columns(len(units))

        for i, unit in enumerate(units):
            unit_value_cols = [c for c in value_cols if unit_map[c] == unit]
            min_default = float(df[unit_value_cols].min().min())
            max_default = float(df[unit_value_cols].max().max())

            with axis_cols[i]:
                st.markdown(f"**{unit}**")

                use_auto = st.checkbox(
                    "Auto",
                    value=True,
                    key=f"{chart_title}_{unit}_auto",
                )

                if use_auto:
                    ranges[unit] = None
                else:
                    ymin = st.number_input(
                        "Min",
                        value=min_default,
                        key=f"{chart_title}_{unit}_min",
                    )
                    ymax = st.number_input(
                        "Max",
                        value=max_default,
                        key=f"{chart_title}_{unit}_max",
                    )
                    ranges[unit] = [ymin, ymax]

    return ranges


def make_multi_axis_plot(df, time_col, value_cols, unit_map, axis_ranges):
    fig = go.Figure()

    units = []
    for col in value_cols:
        unit = unit_map[col]
        if unit not in units:
            units.append(unit)

    axis_map = {
        unit: "y" if i == 0 else f"y{i + 1}"
        for i, unit in enumerate(units)
    }

    for col in value_cols:
        unit = unit_map[col]
        fig.add_trace(
            go.Scatter(
                x=df[time_col],
                y=df[col],
                mode="lines",
                name=col,
                yaxis=axis_map[unit],
            )
        )

    layout = {
        "xaxis": {"title": time_col},
        "yaxis": {
            "title": units[0] if units else "",
            "range": axis_ranges.get(units[0]) if units else None,
        },
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


def safe_div(a, b):
    return a / b if b not in [0, None] and pd.notna(b) else float("nan")


def calculate_summary_table(df):
    total = df.sum(numeric_only=True)

    volume_imbalance_mwh = (
        total.get("delivered_volume_mwh", 0)
        - total.get("nominated_volume_mwh", 0)
    )

    summary = pd.DataFrame(
        index=["Volume", "Revenue", "Capture price", "Share wrt Total", "Share wrt EPEX"],
        columns=["Total", "EPEX", "Imbalance total", "Imbalance long", "Imbalance short"],
        dtype=float,
    )

    # Volumes
    summary.loc["Volume", "Total"] = total.get("delivered_volume_mwh")
    summary.loc["Volume", "EPEX"] = total.get("nominated_volume_mwh")
    summary.loc["Volume", "Imbalance total"] = volume_imbalance_mwh
    summary.loc["Volume", "Imbalance long"] = total.get("volume_long_mwh")
    summary.loc["Volume", "Imbalance short"] = total.get("volume_short_mwh")

    # Revenues
    summary.loc["Revenue", "Total"] = total.get("total_revenue")
    summary.loc["Revenue", "EPEX"] = total.get("epex_revenue")
    summary.loc["Revenue", "Imbalance total"] = total.get("imbalance_total_revenue")
    summary.loc["Revenue", "Imbalance long"] = total.get("imbalance_long_revenue")
    summary.loc["Revenue", "Imbalance short"] = total.get("imbalance_short_revenue")

    # Capture prices
    summary.loc["Capture price", "Total"] = safe_div(
        summary.loc["Revenue", "Total"],
        summary.loc["Volume", "Total"],
    )
    summary.loc["Capture price", "EPEX"] = safe_div(
        summary.loc["Revenue", "EPEX"],
        summary.loc["Volume", "EPEX"],
    )
    summary.loc["Capture price", "Imbalance total"] = safe_div(
        summary.loc["Revenue", "Imbalance total"],
        abs(summary.loc["Volume", "Imbalance total"]),
    )
    summary.loc["Capture price", "Imbalance long"] = safe_div(
        summary.loc["Revenue", "Imbalance long"],
        summary.loc["Volume", "Imbalance long"],
    )
    summary.loc["Capture price", "Imbalance short"] = safe_div(
        summary.loc["Revenue", "Imbalance short"],
        summary.loc["Volume", "Imbalance short"],
    )

    # Revenue shares
    for col in summary.columns:
        summary.loc["Share wrt Total", col] = safe_div(
            summary.loc["Revenue", col],
            summary.loc["Revenue", "Total"],
        )
        
    for col in summary.columns:
        summary.loc["Share wrt EPEX", col] = safe_div(
            summary.loc["Revenue", col],
            summary.loc["Revenue", "EPEX"],
        )

    return summary


def format_summary_table(summary):
    formatted = summary.astype("object").copy()

    for col in formatted.columns:
        formatted.loc["Volume", col] = f"{summary.loc['Volume', col]:,.0f} MWh"
        formatted.loc["Revenue", col] = f"€{summary.loc['Revenue', col]:,.0f}"
        formatted.loc["Capture price", col] = f"{summary.loc['Capture price', col]:,.2f} €/MWh"
        formatted.loc["Share wrt Total", col] = f"{summary.loc['Share wrt Total', col]:.1%}"
        formatted.loc["Share wrt EPEX", col] = f"{summary.loc['Share wrt EPEX', col]:.1%}"

    return formatted




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
    return sorted(
        blob.name
        for blob in container.list_blobs(name_starts_with=prefix)
        if blob.name.endswith(".csv")
    )


@st.cache_data(ttl=300)
def read_blob_csv(blob_name):
    container = get_container_client()
    blob_bytes = container.download_blob(blob_name).readall()
    return pd.read_csv(BytesIO(blob_bytes))


selected_blob = None

with st.sidebar:
    st.header("Data source")

    dataset_type = st.radio(
        "Choose dataset",
        ["Monthly file", "YTD export"],
        key="dataset_type",
    )

    if dataset_type == "Monthly file":
        monthly_blob_names = list_csv_blobs("monthly/")

        years = sorted({
            name.split("/")[1]
            for name in monthly_blob_names
            if len(name.split("/")) >= 3
        })

        if not years:
            st.error("No monthly files found in Blob Storage under monthly/YYYY/")
            st.stop()

        selected_year = st.selectbox(
            "Year",
            years,
            key="selected_year",
        )

        monthly_files = list_csv_blobs(f"monthly/{selected_year}/")

        selected_blob = st.selectbox(
            "Month",
            monthly_files,
            format_func=lambda x: x.split("/")[-1].replace(".csv", ""),
            key="selected_month_blob",
        )

    else:
        export_files = list_csv_blobs("exports/")

        if not export_files:
            st.error("No YTD export files found in Blob Storage under exports/")
            st.stop()

        selected_blob = st.selectbox(
            "YTD export",
            export_files,
            format_func=lambda x: x.split("/")[-1].replace(".csv", ""),
            key="selected_ytd_blob",
        )


if not selected_blob:
    st.info("Choose a dataset to start.")
    st.stop()


df = read_blob_csv(selected_blob)
st.caption(f"Loaded from Azure Blob Storage: `{selected_blob}`")

time_candidates = [
    c for c in df.columns
    if "timestamp" in c.lower() or "date" in c.lower() or "time" in c.lower()
]

default_time_col = "timestamp_Ams" if "timestamp_Ams" in df.columns else (
    time_candidates[0] if time_candidates else df.columns[0]
)

with st.sidebar:
    st.header("Controls")

    time_col = st.selectbox(
        "Timestamp column",
        df.columns,
        index=list(df.columns).index(default_time_col),
        key="timestamp_column_selector",
    )

df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
df = df.dropna(subset=[time_col]).sort_values(time_col)

min_date = df[time_col].min().date()
max_date = df[time_col].max().date()

with st.sidebar:
    date_range = st.date_input(
        "Date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
        key="date_range",
    )

    rule = st.selectbox(
        "Resampling frequency",
        ["Original", "15min", "h", "D", "W", "ME", "YE"],
        format_func=lambda x: {
            "Original": "Original",
            "15min": "15 minutes",
            "h": "Hourly",
            "D": "Daily",
            "W": "Weekly",
            "ME": "Monthly",
            "YE": "Yearly",
        }[x],
        key="resampling_frequency",
    )

if len(date_range) == 2:
    start_date, end_date = date_range
    df = df[
        (df[time_col].dt.date >= start_date)
        & (df[time_col].dt.date <= end_date)
    ]

numeric_cols = [
    col for col in df.columns
    if col != time_col and pd.api.types.is_numeric_dtype(df[col])
]

summary_table = calculate_summary_table(df)

st.header("Summary")

c1, c2, c3, c4 = st.columns(4)

c1.metric("Delivered volume", f"{summary_table.loc['Volume', 'Total']:,.0f} MWh")
c2.metric("Nominated volume", f"{summary_table.loc['Volume', 'EPEX']:,.0f} MWh")
c3.metric("Total revenue", f"€{summary_table.loc['Revenue', 'Total']:,.0f}")
c4.metric("Total capture", f"{summary_table.loc['Capture price', 'Total']:,.2f} €/MWh")

st.header("Breakdown")
st.dataframe(
    format_summary_table(summary_table),
    use_container_width=True,
)

chart_groups = {
    "1) Volumes and EPEX price": [
        "nominated_volume_mwh",
        "delivered_volume_mwh",
        "epex_eur_per_mwh",
    ],
    "2) Revenues": [
        "total_revenue",
        "epex_revenue",
        "imbalance_total_revenue",
        "imbalance_short_revenue",
        "imbalance_long_revenue",
    ],
    "3) Imbalance prices": [
        "imbalance_total_revenue",
        "imbalance_long_eur_per_mwh",
        "imbalance_short_eur_per_mwh",
    ],
}

available_groups = {
    title: [c for c in cols if c in numeric_cols]
    for title, cols in chart_groups.items()
}

all_chart_cols = sorted(
    set(c for cols in available_groups.values() for c in cols)
)

if all_chart_cols:
    unit_map = {col: infer_unit(col) for col in all_chart_cols}
    plot_df = resample_df(df, time_col, all_chart_cols, rule)

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

            fig = make_multi_axis_plot(
                plot_df,
                time_col,
                cols,
                unit_map,
                axis_ranges,
            )

            st.plotly_chart(fig, use_container_width=True)
else:
    st.info("None of the predefined chart columns were found.")
