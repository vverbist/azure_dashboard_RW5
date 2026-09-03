from __future__ import annotations

import calendar

import numpy as np
import pandas as pd

from .calculations import safe_div
from .formatting import format_value
from .metadata import CURRENCY_UNIT, PRICE_UNIT

PERIODS_PER_HOUR = 4

MONTHLY_NUMERIC_COLUMNS = [
    "Delivered volume MWh",
    "Total revenue EUR",
    "Total capture price EUR/MWh",
    "EPEX-only revenue EUR",
    "EPEX-only capture price EUR/MWh",
    "Imbalance settlement cash flow EUR",
    "Imbalance gain/loss vs day-ahead EUR",
    "Imbalance volume short MWh",
    "Imbalance volume long MWh",
    "Below-strike revenue EUR",
    "Below-strike hours",
    "Greenchoice benchmark EUR",
]

MONTHLY_KPI_FORMATS = [
    ("Delivered volume", "Delivered volume MWh", "MWh", 0),
    ("Total revenue", "Total revenue EUR", CURRENCY_UNIT, 2),
    ("Total capture price", "Total capture price EUR/MWh", PRICE_UNIT, 2),
    ("Greenchoice benchmark", "Greenchoice benchmark EUR", CURRENCY_UNIT, 2),
    ("EPEX-only revenue", "EPEX-only revenue EUR", CURRENCY_UNIT, 2),
    ("EPEX-only capture price", "EPEX-only capture price EUR/MWh", PRICE_UNIT, 2),
    ("Imbalance settlement cash flow", "Imbalance settlement cash flow EUR", CURRENCY_UNIT, 2),
    ("Imbalance gain/loss vs day-ahead", "Imbalance gain/loss vs day-ahead EUR", CURRENCY_UNIT, 2),
    ("Imbalance volume short", "Imbalance volume short MWh", "MWh", 0),
    ("Imbalance volume long", "Imbalance volume long MWh", "MWh", 0),
    ("Below-strike revenue", "Below-strike revenue EUR", CURRENCY_UNIT, 2),
    ("Below-strike hours", "Below-strike hours", "hours", 2),
    
]


def count_below_strike_hours(period_df: pd.DataFrame) -> float:
    if "is_below_strike" not in period_df.columns:
        return np.nan
    return period_df["is_below_strike"].fillna(False).astype(bool).sum() / PERIODS_PER_HOUR


def calculate_period_numeric(period_df: pd.DataFrame) -> dict[str, float]:
    total = period_df.sum(numeric_only=True, min_count=1)
    delivered = total.get("delivered_volume_mwh", np.nan)
    nominated = total.get("nominated_volume_mwh", np.nan)
    total_revenue = total.get("total_revenue", np.nan)
    epex_revenue = total.get("epex_revenue", np.nan)

    return {
        "Delivered volume MWh": delivered,
        "Total revenue EUR": total_revenue,
        "Total capture price EUR/MWh": safe_div(total_revenue, delivered),
        "Greenchoice benchmark EUR": total.get("greenchoice_revenue", np.nan),
        "EPEX-only revenue EUR": epex_revenue,
        "EPEX-only capture price EUR/MWh": safe_div(epex_revenue, nominated),
        "Imbalance settlement cash flow EUR": total.get("imbalance_total_revenue", np.nan),
        "Imbalance gain/loss vs day-ahead EUR": total.get(
            "imbalance_gain_loss_vs_day_ahead_calc", np.nan
        ),
        "Imbalance volume short MWh": total.get("volume_short_mwh", np.nan),
        "Imbalance volume long MWh": total.get("volume_long_mwh", np.nan),
        "Below-strike revenue EUR": total.get("strike_nomination_revenue", np.nan),
        "Below-strike hours": count_below_strike_hours(period_df),
        
    }


def calculate_period_kpis(period_df: pd.DataFrame) -> dict[str, str]:
    values = calculate_period_numeric(period_df)
    return {
        label: format_value(values[numeric_key], unit, decimals=decimals)
        for label, numeric_key, unit, decimals in MONTHLY_KPI_FORMATS
    }


def make_monthly_kpi_table(period_df: pd.DataFrame, time_col: str) -> pd.DataFrame:
    if period_df.empty:
        return pd.DataFrame()

    work = period_df.copy()
    work["month_period"] = work[time_col].dt.to_period("M")
    months = sorted(work["month_period"].dropna().unique())
    kpi_names = [label for label, *_ in MONTHLY_KPI_FORMATS]

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


def make_monthly_numeric_table(period_df: pd.DataFrame, time_col: str) -> pd.DataFrame:
    if period_df.empty:
        return pd.DataFrame()
    work = period_df.copy()
    work["Month"] = work[time_col].dt.to_period("M").astype(str)
    rows = []
    for month, month_df in work.groupby("Month", sort=True):
        rows.append({"Month": month, **calculate_period_numeric(month_df)})

    rows.append({"Month": "YTD total", **calculate_period_numeric(work)})
    return pd.DataFrame(rows, columns=["Month", *MONTHLY_NUMERIC_COLUMNS])


def make_monthly_chart_source(period_df: pd.DataFrame, time_col: str) -> pd.DataFrame:
    numeric = make_monthly_numeric_table(period_df, time_col)
    if numeric.empty:
        return numeric
    return numeric[numeric["Month"] != "YTD total"].copy()


# Metrics that scale with elapsed time (revenue, volumes) and can be projected to a full
# month by run-rate. Rates/means (capture price €/MWh) and derived hours are excluded.
EXTRAPOLATABLE_UNITS = {CURRENCY_UNIT, "MWh"}
ADDITIVE_MONTHLY_METRICS = [
    numeric_key for _, numeric_key, unit, _ in MONTHLY_KPI_FORMATS if unit in EXTRAPOLATABLE_UNITS
]


def month_coverage(full_df: pd.DataFrame, time_col: str) -> dict[str, dict]:
    """Per-month calendar coverage. A month is 'partial' when the dataset does not
    reach its last calendar day (typically the current, not-yet-elapsed month), so the
    frontend can mark it and avoid comparing it head-to-head with completed months.
    Keyed by period string, e.g. '2026-07'."""
    if full_df.empty or time_col not in full_df.columns:
        return {}

    times = pd.to_datetime(full_df[time_col], errors="coerce").dropna()
    if times.empty:
        return {}

    out: dict[str, dict] = {}
    for period, last_ts in times.groupby(times.dt.to_period("M")).max().items():
        days_in_month = calendar.monthrange(period.year, period.month)[1]
        out[str(period)] = {
            "label": f"{calendar.month_abbr[period.month]} {period.year}",
            "days_in_month": days_in_month,
            "days_covered": int(last_ts.day),
            "coverage_through": last_ts.date().isoformat(),
            "is_partial": bool(last_ts.day < days_in_month),
        }
    return out


def monthly_projection(full_df: pd.DataFrame, time_col: str) -> dict[str, dict]:
    """Run-rate projection of a partial month's additive metrics to a full month.

    Scales by elapsed-day fraction (days_in_month / days_covered) and lists which metrics
    may be projected. This is a naive linear estimate, not a forecast; the frontend labels
    it as projected. Keyed by period string, e.g. '2026-07'."""
    projection: dict[str, dict] = {}
    for month, info in month_coverage(full_df, time_col).items():
        if not info["is_partial"] or info["days_covered"] == 0:
            continue
        projection[month] = {
            "days_covered": info["days_covered"],
            "days_in_month": info["days_in_month"],
            "factor": info["days_in_month"] / info["days_covered"],
            "metrics": ADDITIVE_MONTHLY_METRICS,
        }
    return projection
