from __future__ import annotations

import pandas as pd

from .metadata import CURRENCY_UNIT, PRICE_UNIT


def format_value(value, unit: str, decimals: int = 2) -> str:
    if pd.isna(value):
        return "-"
    if unit in {CURRENCY_UNIT, "EUR"}:
        return f"€{value:,.0f}"
    if unit in {PRICE_UNIT, "EUR/MWh"}:
        return f"{value:,.{decimals}f} €/MWh"
    if unit == "MWh":
        return f"{value:,.{decimals}f} MWh"
    if unit == "%":
        return f"{value:,.2%}" if abs(value) <= 1 else f"{value:,.2f}%"
    if unit == "ratio":
        return f"{value:,.3f}"
    if unit == "count":
        return f"{int(value):,}" if pd.notna(value) else "-"
    if unit == "hours":
        return f"{value:,.{decimals}f} h"
    return f"{value:,.2f}"


def format_summary_table(summary: pd.DataFrame) -> pd.DataFrame:
    formatted = summary.astype("object").copy()
    for col in formatted.columns:
        formatted.loc["Volume", col] = format_value(summary.loc["Volume", col], "MWh", decimals=0)
        formatted.loc["Revenue", col] = format_value(summary.loc["Revenue", col], CURRENCY_UNIT)
        formatted.loc["Capture price", col] = format_value(summary.loc["Capture price", col], PRICE_UNIT)
        formatted.loc["Share wrt Total", col] = format_value(summary.loc["Share wrt Total", col], "%")
        formatted.loc["Share wrt EPEX", col] = format_value(summary.loc["Share wrt EPEX", col], "%")
    return formatted


def format_generic_metric_table(table: pd.DataFrame) -> pd.DataFrame:
    if table.empty:
        return table
    out = table.copy()
    out["Value"] = [format_value(v, u) for v, u in zip(out["Value"], out["Unit"])]
    return out.drop(columns=["Unit"])


def format_variance_table(table: pd.DataFrame) -> pd.DataFrame:
    return format_generic_metric_table(table)
