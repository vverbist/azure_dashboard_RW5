from __future__ import annotations

import numpy as np
import pandas as pd

from .formatting import format_value
from .metadata import existing, infer_unit, pretty_name


def build_anomaly_table(
    df: pd.DataFrame,
    time_col: str,
    metric: str,
    n: int = 10,
    largest: bool = True,
    title: str = "Anomaly",
) -> pd.DataFrame:
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
    display_cols = [time_col, "Where is the anomaly?", "Impact"] + [
        c for c in raw.columns if c not in [time_col, "Where is the anomaly?", "Impact", metric]
    ]
    out = raw[display_cols].rename(columns={c: pretty_name(c) for c in display_cols if c not in [time_col, "Where is the anomaly?", "Impact"]})
    return out


def top_periods(df: pd.DataFrame, time_col: str, metric: str, n: int = 10, largest: bool = True) -> pd.DataFrame:
    if metric not in df.columns:
        return pd.DataFrame()
    cols = [time_col, metric]
    extra_cols = existing(["delivered_volume_mwh", "nominated_volume_mwh", "epex_eur_per_mwh", "imbalance_long_eur_per_mwh", "imbalance_short_eur_per_mwh"], df)
    cols += [c for c in extra_cols if c not in cols]
    result = df[cols].dropna(subset=[metric]).sort_values(metric, ascending=not largest).head(n)
    return result.rename(columns={c: pretty_name(c) for c in result.columns})

