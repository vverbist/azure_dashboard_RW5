from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .formatting import format_value
from .metadata import CURRENCY_UNIT, PRICE_UNIT, agg_for_col


def safe_div(a, b):
    return a / b if b not in [0, None] and pd.notna(b) else np.nan


def normalize_percentage(value: float | int | None, default: float = 17.0) -> float:
    """Convert a percentage number to a fraction: 17 -> 0.17, 0.5 -> 0.005, 100 -> 1.0.

    The input is always interpreted as a percentage. There is no "values <= 1 are
    already fractions" heuristic, so `1` unambiguously means 1% and `100` means 100%.
    A `None` value falls back to `default`, which is itself a percentage number.
    """
    if value is None:
        value = default
    return float(value) / 100.0


def parse_time_column(df: pd.DataFrame, time_col: str) -> pd.DataFrame:
    out = df.copy()
    if time_col not in out.columns:
        raise ValueError(f"Timestamp column '{time_col}' was not found.")
    out[time_col] = pd.to_datetime(out[time_col], errors="coerce")
    return out.dropna(subset=[time_col]).sort_values(time_col)


def filter_by_date_range(
    df: pd.DataFrame,
    time_col: str,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
) -> pd.DataFrame:
    out = df.copy()
    if start_date is not None and end_date is not None:
        if pd.Timestamp(start_date).date() > pd.Timestamp(end_date).date():
            raise ValueError("start_date must be on or before end_date.")
    if start_date is not None:
        start = pd.Timestamp(start_date).date()
        out = out[out[time_col].dt.date >= start]
    if end_date is not None:
        end = pd.Timestamp(end_date).date()
        out = out[out[time_col].dt.date <= end]
    return out


def resample_df(df: pd.DataFrame, time_col: str, value_cols: list[str], rule: str) -> pd.DataFrame:
    if not value_cols:
        return df[[time_col]].copy()
    if rule == "Original":
        return df[[time_col] + value_cols].copy()
    temp = df[[time_col] + value_cols].copy().set_index(time_col)
    agg_map = {col: agg_for_col(col) for col in value_cols}
    return temp.resample(rule).agg(agg_map).reset_index()


def aggregate_values(df: pd.DataFrame, value_cols: list[str], unit_map: dict[str, str]) -> dict[str, str]:
    values = {}
    for col in value_cols:
        agg = agg_for_col(col)
        value = df[col].sum(min_count=1) if agg == "sum" else df[col].mean()
        values[col] = format_value(value, unit_map[col])
    return values


def calculate_summary_table(df: pd.DataFrame) -> pd.DataFrame:
    total = df.sum(numeric_only=True, min_count=1)
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


def add_diagnostic_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if {"delivered_volume_mwh", "nominated_volume_mwh"}.issubset(out.columns):
        out["imbalance_volume_mwh_calc"] = out["delivered_volume_mwh"] - out["nominated_volume_mwh"]
        out["abs_imbalance_volume_mwh_calc"] = out["imbalance_volume_mwh_calc"].abs()
    if {"total_revenue", "epex_revenue"}.issubset(out.columns):
        out["revenue_vs_epex_calc"] = out["total_revenue"] - out["epex_revenue"]
    if {"delivered_volume_mwh", "epex_eur_per_mwh"}.issubset(out.columns):
        out["delivered_day_ahead_value_calc"] = (
            out["delivered_volume_mwh"] * out["epex_eur_per_mwh"]
        )
    if {"total_revenue", "delivered_day_ahead_value_calc"}.issubset(out.columns):
        out["imbalance_gain_loss_vs_day_ahead_calc"] = (
            out["total_revenue"] - out["delivered_day_ahead_value_calc"]
        )
    if {"total_revenue", "delivered_volume_mwh"}.issubset(out.columns):
        out["capture_total_calc"] = out["total_revenue"] / out["delivered_volume_mwh"].replace(0, np.nan)
    if {"epex_revenue", "nominated_volume_mwh"}.issubset(out.columns):
        out["capture_epex_calc"] = out["epex_revenue"] / out["nominated_volume_mwh"].replace(0, np.nan)
    if {"capture_total_calc", "capture_epex_calc"}.issubset(out.columns):
        out["capture_spread_vs_epex_calc"] = out["capture_total_calc"] - out["capture_epex_calc"]
    return out


def make_variance_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    total = df.sum(numeric_only=True, min_count=1)
    if {"total_revenue", "epex_revenue"}.issubset(df.columns):
        if "revenue_vs_epex_calc" in df.columns:
            settlement_cash_flow = df["revenue_vs_epex_calc"].sum(min_count=1)
        else:
            settlement_cash_flow = (
                df["total_revenue"] - df["epex_revenue"]
            ).sum(min_count=1)
        rows.append({
            "Metric": "Imbalance settlement cash flow",
            "Value": settlement_cash_flow,
            "Unit": CURRENCY_UNIT,
            "Interpretation": "Cash settled on delivered-minus-nominated volume; this is not the economic gain or loss from imbalance.",
        })
    if {"total_revenue", "delivered_volume_mwh", "epex_eur_per_mwh"}.issubset(df.columns):
        if "imbalance_gain_loss_vs_day_ahead_calc" in df.columns:
            gain_loss_vs_day_ahead = df[
                "imbalance_gain_loss_vs_day_ahead_calc"
            ].sum(min_count=1)
        else:
            gain_loss_vs_day_ahead = (
                df["total_revenue"]
                - df["delivered_volume_mwh"] * df["epex_eur_per_mwh"]
            ).sum(min_count=1)
        rows.append({
            "Metric": "Imbalance gain/loss vs day-ahead",
            "Value": gain_loss_vs_day_ahead,
            "Unit": CURRENCY_UNIT,
            "Interpretation": "Total revenue minus actual delivered volume valued at each interval's EPEX price; positive is a gain and negative is a cost.",
        })
    if {"delivered_volume_mwh", "nominated_volume_mwh"}.issubset(df.columns):
        delivered = total.get("delivered_volume_mwh", np.nan)
        nominated = total.get("nominated_volume_mwh", np.nan)
        rows.append({"Metric": "Delivered vs nominated volume", "Value": delivered - nominated, "Unit": "MWh", "Interpretation": "Positive means delivered volume exceeded nomination."})
    if {"capture_total_calc", "capture_epex_calc"}.issubset(df.columns):
        total_capture = safe_div(total.get("total_revenue", np.nan), total.get("delivered_volume_mwh", np.nan))
        epex_capture = safe_div(total.get("epex_revenue", np.nan), total.get("nominated_volume_mwh", np.nan))
        rows.append({"Metric": "Capture spread vs EPEX", "Value": total_capture - epex_capture, "Unit": PRICE_UNIT, "Interpretation": "Positive means total capture beat EPEX capture."})
    return pd.DataFrame(rows)

