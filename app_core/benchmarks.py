from __future__ import annotations

import numpy as np
import pandas as pd

from .calculations import safe_div
from .metadata import CURRENCY_UNIT, PRICE_UNIT


def choose_default_volume_column(df: pd.DataFrame) -> str | None:
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


def add_greenchoice_benchmark(
    df: pd.DataFrame,
    volume_col: str | None,
    epex_col: str | None,
    afslag_pct: float,
    afslag_min: float,
    gvo: float,
) -> pd.DataFrame:
    out = df.copy()
    required = [volume_col, epex_col]
    if not volume_col or not epex_col or any(c not in out.columns for c in required):
        return out

    afslag_variable = out[epex_col] * afslag_pct
    # The floor means Greenchoice receives at least the minimum discount versus EPEX.
    # For negative EPEX prices, this still applies as a fixed EUR/MWh discount.
    out["greenchoice_afslag_eur_per_mwh"] = np.maximum(afslag_variable, afslag_min)
    out["greenchoice_net_price_eur_per_mwh"] = out[epex_col] - out["greenchoice_afslag_eur_per_mwh"] + gvo
    out["greenchoice_billable_price_eur_per_mwh"] = out["greenchoice_net_price_eur_per_mwh"].clip(lower=0)
    out["greenchoice_revenue"] = out[volume_col] * out["greenchoice_billable_price_eur_per_mwh"]
    if "total_revenue" in out.columns:
        out["revenue_vs_greenchoice_calc"] = out["total_revenue"] - out["greenchoice_revenue"]
    return out


def add_strike_price_diagnostic(
    df: pd.DataFrame,
    epex_col: str | None,
    nomination_col: str | None,
    strike_price: float,
) -> pd.DataFrame:
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


def summarize_greenchoice(df: pd.DataFrame) -> pd.DataFrame:
    if "greenchoice_revenue" not in df.columns:
        return pd.DataFrame()
    total = df.sum(numeric_only=True)
    greenchoice = total.get("greenchoice_revenue", np.nan)
    actual = total.get("total_revenue", np.nan)
    volume = total.get("delivered_volume_mwh", np.nan)
    if pd.isna(volume) or volume == 0:
        volume = total.get("nominated_volume_mwh", np.nan)
    rows = [
        {"Metric": "Greenchoice benchmark revenue", "Value": greenchoice, "Unit": CURRENCY_UNIT, "Interpretation": "AAP volume x max(EPEX - afslag + GvO, 0)."},
        {"Metric": "Greenchoice benchmark capture", "Value": safe_div(greenchoice, volume), "Unit": PRICE_UNIT, "Interpretation": "Benchmark revenue divided by the selected AAP/delivered volume."},
    ]
    if pd.notna(actual):
        rows.append({"Metric": "Actual vs Greenchoice", "Value": actual - greenchoice, "Unit": CURRENCY_UNIT, "Interpretation": "Positive means the actual result beat the Greenchoice benchmark."})
    return pd.DataFrame(rows)


def summarize_strike_price(df: pd.DataFrame) -> pd.DataFrame:
    if "strike_nomination_revenue" not in df.columns:
        return pd.DataFrame()
    below = df[df.get("is_below_strike", False)]
    total_revenue = df["strike_nomination_revenue"].sum()
    total_volume = df["strike_volume_mwh"].sum() if "strike_volume_mwh" in df.columns else np.nan
    rows = [
        {"Metric": "Periods below strike", "Value": len(below), "Unit": "count", "Interpretation": "Number of rows where EPEX was below the configured strike price."},
        {"Metric": "Nominated volume below strike", "Value": total_volume, "Unit": "MWh", "Interpretation": "Nominated volume exposed during below-strike periods."},
        {"Metric": "Nomination revenue below strike", "Value": total_revenue, "Unit": CURRENCY_UNIT, "Interpretation": "Nominated volume x EPEX price during below-strike periods."},
    ]
    return pd.DataFrame(rows)

