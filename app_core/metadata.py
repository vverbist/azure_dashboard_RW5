from __future__ import annotations

import re

import pandas as pd


CURRENCY_UNIT = "€"
PRICE_UNIT = "€/MWh"

TIMESTAMP_COLUMNS = ["timestamp_Ams", "timestamp_UTC", "timestamp_utc", "timestamp"]
GREENCHOICE_VOLUME_COL = "delivered_volume_mwh"
EPEX_PRICE_COL = "epex_eur_per_mwh"
NOMINATION_VOLUME_COL = "nominated_volume_mwh"

RESAMPLING_RULES = ["Original", "15min", "h", "D", "W", "ME", "YE"]

COLUMN_METADATA = {
    "delivered_volume_mwh": {"unit": "MWh", "aggregation": "sum", "label": "Delivered volume"},
    "nominated_volume_mwh": {"unit": "MWh", "aggregation": "sum", "label": "Nominated volume"},
    "volume_long_mwh": {"unit": "MWh", "aggregation": "sum", "label": "Long imbalance volume"},
    "volume_short_mwh": {"unit": "MWh", "aggregation": "sum", "label": "Short imbalance volume"},
    "total_revenue": {"unit": CURRENCY_UNIT, "aggregation": "sum", "label": "Total revenue"},
    "epex_revenue": {"unit": CURRENCY_UNIT, "aggregation": "sum", "label": "EPEX revenue"},
    "imbalance_total_revenue": {"unit": CURRENCY_UNIT, "aggregation": "sum", "label": "Total imbalance revenue"},
    "imbalance_long_revenue": {"unit": CURRENCY_UNIT, "aggregation": "sum", "label": "Long imbalance revenue"},
    "imbalance_short_revenue": {"unit": CURRENCY_UNIT, "aggregation": "sum", "label": "Short imbalance revenue"},
    "epex_eur_per_mwh": {"unit": PRICE_UNIT, "aggregation": "mean", "label": "EPEX price"},
    "imbalance_long_eur_per_mwh": {"unit": PRICE_UNIT, "aggregation": "mean", "label": "Long imbalance price"},
    "imbalance_short_eur_per_mwh": {"unit": PRICE_UNIT, "aggregation": "mean", "label": "Short imbalance price"},
    "revenue_vs_epex_calc": {"unit": CURRENCY_UNIT, "aggregation": "sum", "label": "Revenue vs EPEX"},
    "imbalance_volume_mwh_calc": {"unit": "MWh", "aggregation": "sum", "label": "Net imbalance volume"},
    "abs_imbalance_volume_mwh_calc": {"unit": "MWh", "aggregation": "sum", "label": "Absolute imbalance volume"},
    "capture_total_calc": {"unit": PRICE_UNIT, "aggregation": "mean", "label": "Total capture"},
    "capture_epex_calc": {"unit": PRICE_UNIT, "aggregation": "mean", "label": "EPEX capture"},
    "capture_spread_vs_epex_calc": {"unit": PRICE_UNIT, "aggregation": "mean", "label": "Capture spread vs EPEX"},
    "greenchoice_afslag_eur_per_mwh": {"unit": PRICE_UNIT, "aggregation": "mean", "label": "Greenchoice afslag"},
    "greenchoice_net_price_eur_per_mwh": {"unit": PRICE_UNIT, "aggregation": "mean", "label": "Greenchoice net price"},
    "greenchoice_billable_price_eur_per_mwh": {"unit": PRICE_UNIT, "aggregation": "mean", "label": "Greenchoice billable price"},
    "greenchoice_revenue": {"unit": CURRENCY_UNIT, "aggregation": "sum", "label": "Greenchoice benchmark revenue"},
    "revenue_vs_greenchoice_calc": {"unit": CURRENCY_UNIT, "aggregation": "sum", "label": "Revenue vs Greenchoice"},
    "strike_nomination_revenue": {"unit": CURRENCY_UNIT, "aggregation": "sum", "label": "Nomination revenue below strike"},
}

CHART_GROUPS = {
    "Volumes": ["nominated_volume_mwh", "delivered_volume_mwh", "imbalance_volume_mwh_calc"],
    "Revenue components": ["total_revenue", "epex_revenue", "imbalance_total_revenue", "greenchoice_revenue"],
    "Prices": ["epex_eur_per_mwh","imbalance_long_eur_per_mwh", "imbalance_short_eur_per_mwh"],
}

ANOMALY_SPECS = {
    "negative-imbalance-revenue": {
        "label": "Large negative imbalance revenue",
        "metric": "imbalance_total_revenue",
        "largest": False,
        "file_name": "anomaly_negative_imbalance_revenue.csv",
        "description": "Periods with the largest negative imbalance revenue.",
    },
    "positive-imbalance-revenue": {
        "label": "Large positive imbalance revenue",
        "metric": "imbalance_total_revenue",
        "largest": True,
        "file_name": "anomaly_positive_imbalance_revenue.csv",
        "description": "Periods with the largest positive imbalance revenue.",
    },
    "negative-epex-revenue": {
        "label": "Negative EPEX revenue",
        "metric": "epex_revenue",
        "largest": False,
        "file_name": "anomaly_negative_epex_revenue.csv",
        "description": "Periods with the most negative nominated EPEX revenue.",
    },
}


def pretty_name(col: str) -> str:
    return COLUMN_METADATA.get(col, {}).get("label", col.replace("_", " ").title())


def infer_unit(col: str) -> str:
    if col in COLUMN_METADATA:
        return COLUMN_METADATA[col]["unit"]

    c = col.lower()
    if "eur_per_mwh" in c or "price" in c or "capture" in c:
        return PRICE_UNIT
    if "revenue" in c:
        return CURRENCY_UNIT
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


def agg_for_col(col: str) -> str:
    if col in COLUMN_METADATA:
        return COLUMN_METADATA[col]["aggregation"]

    c = col.lower()
    if "eur_per_mwh" in c or "capture" in c or "performance" in c or "share" in c:
        return "mean"
    if "mwh" in c or "volume" in c or "revenue" in c:
        return "sum"
    return "mean"


def existing(cols: list[str], df: pd.DataFrame) -> list[str]:
    return [c for c in cols if c in df.columns]


def numeric_columns(df: pd.DataFrame, excluded: str | None = None) -> list[str]:
    return [
        col
        for col in df.columns
        if col != excluded and pd.api.types.is_numeric_dtype(df[col])
    ]


def timestamp_column_options(df: pd.DataFrame) -> list[str]:
    known = [col for col in TIMESTAMP_COLUMNS if col in df.columns]
    inferred = [
        col
        for col in df.columns
        if col not in known and any(token in col.lower() for token in ["timestamp", "date", "time"])
    ]
    return known + inferred
