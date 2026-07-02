from __future__ import annotations

import calendar

import numpy as np
import pandas as pd

from .calculations import safe_div
from .formatting import format_value
from .metadata import CURRENCY_UNIT, PRICE_UNIT


def calculate_period_kpis(period_df: pd.DataFrame) -> dict[str, str]:
    total = period_df.sum(numeric_only=True)
    delivered = total.get("delivered_volume_mwh", np.nan)
    total_revenue = total.get("total_revenue", np.nan)
    epex_revenue = total.get("epex_revenue", np.nan)
    greenchoice_revenue = total.get("greenchoice_revenue", np.nan)
    strike_revenue = total.get("strike_nomination_revenue", np.nan)
    imbalance_volume = total.get("imbalance_volume_mwh_calc", np.nan)

    return {
        "Delivered volume": format_value(delivered, "MWh", decimals=0),
        "Total revenue": format_value(total_revenue, CURRENCY_UNIT),
        "EPEX revenue": format_value(epex_revenue, CURRENCY_UNIT),
        "Greenchoice revenue": format_value(greenchoice_revenue, CURRENCY_UNIT),
        "Capture price": format_value(safe_div(total_revenue, delivered), PRICE_UNIT),
        "Net imbalance volume": format_value(imbalance_volume, "MWh", decimals=0),
        "Below-strike revenue": format_value(strike_revenue, CURRENCY_UNIT),
    }


def make_monthly_kpi_table(period_df: pd.DataFrame, time_col: str) -> pd.DataFrame:
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


def make_monthly_numeric_table(period_df: pd.DataFrame, time_col: str) -> pd.DataFrame:
    if period_df.empty:
        return pd.DataFrame()
    work = period_df.copy()
    work["Month"] = work[time_col].dt.to_period("M").astype(str)
    grouped = work.groupby("Month").sum(numeric_only=True)
    rows = []
    for month, total in grouped.iterrows():
        delivered = total.get("delivered_volume_mwh", np.nan)
        total_revenue = total.get("total_revenue", np.nan)
        rows.append({
            "Month": month,
            "Delivered volume MWh": delivered,
            "Total revenue EUR": total_revenue,
            "EPEX revenue EUR": total.get("epex_revenue", np.nan),
            "Greenchoice revenue EUR": total.get("greenchoice_revenue", np.nan),
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


def make_monthly_chart_source(period_df: pd.DataFrame, time_col: str) -> pd.DataFrame:
    numeric = make_monthly_numeric_table(period_df, time_col)
    if numeric.empty:
        return numeric
    return numeric[numeric["Month"] != "YTD total"].copy()

