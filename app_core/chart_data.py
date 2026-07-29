from __future__ import annotations

import numpy as np
import os
import pandas as pd

from .calculations import resample_df
from .formatting import format_value
from .metadata import CHART_GROUPS, CURRENCY_UNIT, PRICE_UNIT, infer_unit, pretty_name
from .serialization import dataframe_records, to_jsonable


DEFAULT_CHART_POINT_BUDGET = 2_000
_AUTO_RULES = (
    ("15min", 15 * 60),
    ("30min", 30 * 60),
    ("h", 60 * 60),
    ("2h", 2 * 60 * 60),
    ("4h", 4 * 60 * 60),
    ("8h", 8 * 60 * 60),
    ("12h", 12 * 60 * 60),
    ("D", 24 * 60 * 60),
    ("2D", 2 * 24 * 60 * 60),
    ("W", 7 * 24 * 60 * 60),
)


def chart_point_budget() -> int:
    try:
        configured = int(
            os.getenv("DASHBOARD_CHART_POINT_BUDGET", str(DEFAULT_CHART_POINT_BUDGET))
        )
    except ValueError:
        return DEFAULT_CHART_POINT_BUDGET
    return max(100, min(configured, 10_000))


def _point_budget_rule(
    df: pd.DataFrame,
    time_col: str,
    requested_rule: str,
    point_budget: int,
) -> tuple[str, pd.DataFrame]:
    """Apply the requested resolution, then enforce a deterministic point ceiling."""
    value_cols = [column for column in df.columns if column != time_col]
    requested = resample_df(df, time_col, value_cols, requested_rule)
    if len(requested) <= point_budget:
        return requested_rule, requested

    timestamps = pd.to_datetime(df[time_col], errors="coerce").dropna()
    if len(timestamps) < 2:
        return requested_rule, requested.head(point_budget)

    span_seconds = max((timestamps.max() - timestamps.min()).total_seconds(), 1)
    target_seconds = span_seconds / max(point_budget - 1, 1)
    selected_rule = _AUTO_RULES[-1][0]
    for candidate, seconds in _AUTO_RULES:
        if seconds >= target_seconds:
            selected_rule = candidate
            break

    budgeted = resample_df(df, time_col, value_cols, selected_rule)
    # Extremely long ranges may still exceed the weekly estimate. Calendar month/year
    # aggregation is deterministic and provides a final bounded fallback.
    for fallback in ("ME", "YE"):
        if len(budgeted) <= point_budget:
            break
        selected_rule = fallback
        budgeted = resample_df(df, time_col, value_cols, selected_rule)
    return selected_rule, budgeted


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


def timeseries_chart_data(
    df: pd.DataFrame,
    time_col: str,
    chart_group: str,
    rule: str,
    *,
    point_budget: int | None = None,
) -> dict:
    group_cols = CHART_GROUPS.get(chart_group, CHART_GROUPS["Volumes"])
    cols = [col for col in group_cols if col in df.columns and pd.api.types.is_numeric_dtype(df[col])]
    budget = point_budget or chart_point_budget()
    source = df[[time_col] + cols]
    applied_rule, plot_df = _point_budget_rule(
        source,
        time_col,
        rule,
        budget,
    )
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
        "requested_resolution": rule,
        "applied_resolution": applied_rule,
        "point_budget": budget,
        "source_rows": len(df),
        "returned_rows": len(plot_df),
        "downsampled": applied_rule != rule or len(plot_df) < len(df),
    }

