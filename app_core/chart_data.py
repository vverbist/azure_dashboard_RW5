from __future__ import annotations

import numpy as np
import pandas as pd

from .calculations import resample_df
from .formatting import format_value
from .metadata import CHART_GROUPS, CURRENCY_UNIT, PRICE_UNIT, infer_unit, pretty_name
from .serialization import dataframe_records, to_jsonable


def revenue_bridge_components(summary: pd.DataFrame) -> list[dict]:
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

    return [
        {"label": label, "value": to_jsonable(value), "measure": measure, "text": format_value(value, CURRENCY_UNIT)}
        for label, value, measure in components
    ]


def greenchoice_bridge_components(df: pd.DataFrame) -> list[dict]:
    total = df.sum(numeric_only=True, min_count=1)
    actual = total.get("total_revenue", np.nan)
    benchmark = total.get("greenchoice_revenue", np.nan)
    delta = total.get("revenue_vs_greenchoice_calc", np.nan)
    if pd.isna(benchmark) or pd.isna(actual):
        return []
    components = [
        ("Greenchoice benchmark", benchmark, "relative"),
        ("Actual delta", delta, "relative"),
        ("Actual revenue", actual, "total"),
    ]
    return [
        {"label": label, "value": to_jsonable(value), "measure": measure, "text": format_value(value, CURRENCY_UNIT)}
        for label, value, measure in components
    ]


def strike_exposure_data(
    df: pd.DataFrame,
    time_col: str,
    epex_col: str,
    strike_price: float,
    strike_summary: pd.DataFrame,
) -> dict:
    series = []
    if epex_col in df.columns:
        series.append({
            "name": epex_col,
            "label": pretty_name(epex_col),
            "unit": PRICE_UNIT,
            "x": [to_jsonable(v) for v in df[time_col]],
            "y": [to_jsonable(v) for v in df[epex_col]],
        })
    return {
        "strike_price": strike_price,
        "series": series,
        "summary": dataframe_records(strike_summary),
    }


def timeseries_chart_data(df: pd.DataFrame, time_col: str, chart_group: str, rule: str) -> dict:
    group_cols = CHART_GROUPS.get(chart_group, CHART_GROUPS["Volumes"])
    cols = [col for col in group_cols if col in df.columns and pd.api.types.is_numeric_dtype(df[col])]
    plot_df = resample_df(df, time_col, cols, rule)
    series = [
        {
            "name": col,
            "label": pretty_name(col),
            "unit": infer_unit(col),
            "x": [to_jsonable(v) for v in plot_df[time_col]],
            "y": [to_jsonable(v) for v in plot_df[col]],
        }
        for col in cols
    ]
    return {
        "group": chart_group,
        "available_groups": list(CHART_GROUPS.keys()),
        "columns": cols,
        "series": series,
        "rows": dataframe_records(plot_df),
    }

