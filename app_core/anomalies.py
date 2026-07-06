from __future__ import annotations

import numpy as np
import pandas as pd

from .formatting import format_value
from .metadata import CURRENCY_UNIT, PRICE_UNIT, existing, infer_unit, pretty_name

PERIODS_PER_HOUR = 4


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


def _event_groups(source: pd.DataFrame, mask: pd.Series, time_col: str) -> list[pd.DataFrame]:
    work = source.loc[mask.fillna(False)].copy()
    if work.empty:
        return []

    work = work.sort_values(time_col)
    breaks = work[time_col].diff().dt.total_seconds().fillna(0) > 15 * 60
    work["_event_id"] = breaks.cumsum()
    return [group.drop(columns=["_event_id"]) for _, group in work.groupby("_event_id", sort=True)]


def _sum(group: pd.DataFrame, col: str) -> float:
    return group[col].sum() if col in group.columns else np.nan


def _mean(group: pd.DataFrame, col: str) -> float:
    return group[col].mean() if col in group.columns else np.nan


def _min(group: pd.DataFrame, col: str) -> float:
    return group[col].min() if col in group.columns else np.nan


def _max(group: pd.DataFrame, col: str) -> float:
    return group[col].max() if col in group.columns else np.nan


def _event_window(group: pd.DataFrame, time_col: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = group[time_col].min()
    end = group[time_col].max() + pd.Timedelta(minutes=15)
    return start, end


def _event_duration_hours(group: pd.DataFrame) -> float:
    return len(group) / PERIODS_PER_HOUR


def _severity_label(value: float) -> str:
    if pd.isna(value):
        return "Review"
    value = abs(value)
    if value >= 1000:
        return "Critical"
    if value >= 250:
        return "High"
    if value > 0:
        return "Medium"
    return "Review"


def _format_timestamp(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if pd.notna(value) else "-"


def _event_record(
    group: pd.DataFrame,
    time_col: str,
    event_type: str,
    driver: str,
    impact_value: float,
    impact_unit: str,
    suggested_check: str,
) -> dict:
    start, end = _event_window(group, time_col)
    duration = _event_duration_hours(group)
    delivered = _sum(group, "delivered_volume_mwh")
    nominated = _sum(group, "nominated_volume_mwh")
    imbalance = _sum(group, "imbalance_volume_mwh_calc")
    long_volume = _sum(group, "volume_long_mwh")
    short_volume = _sum(group, "volume_short_mwh")
    total_revenue = _sum(group, "total_revenue")
    epex_revenue = _sum(group, "epex_revenue")
    imbalance_revenue = _sum(group, "imbalance_total_revenue")
    greenchoice_revenue = _sum(group, "greenchoice_revenue")
    below_strike_revenue = _sum(group, "strike_nomination_revenue")
    avg_epex = _mean(group, "epex_eur_per_mwh")
    min_epex = _min(group, "epex_eur_per_mwh")
    max_epex = _max(group, "epex_eur_per_mwh")

    parts = [
        f"{event_type} lasted {format_value(duration, 'hours')} across {len(group)} periods.",
    ]
    if pd.notna(impact_value):
        parts.append(f"Impact was {format_value(impact_value, impact_unit)}.")
    if pd.notna(avg_epex):
        parts.append(f"Average EPEX was {format_value(avg_epex, PRICE_UNIT)}.")
    if pd.notna(imbalance) and imbalance != 0:
        direction = "long" if imbalance > 0 else "short"
        parts.append(f"Net imbalance was {format_value(imbalance, 'MWh')} ({direction}).")

    return {
        "Event type": event_type,
        "Start": _format_timestamp(start),
        "End": _format_timestamp(end),
        "Duration": format_value(duration, "hours"),
        "Periods": len(group),
        "Severity": _severity_label(impact_value),
        "Likely driver": driver,
        "What happened?": " ".join(parts),
        "Suggested check": suggested_check,
        "Impact": format_value(impact_value, impact_unit),
        "Delivered volume": format_value(delivered, "MWh"),
        "Nominated volume": format_value(nominated, "MWh"),
        "Net imbalance": format_value(imbalance, "MWh"),
        "Long imbalance volume": format_value(long_volume, "MWh"),
        "Short imbalance volume": format_value(short_volume, "MWh"),
        "Total revenue": format_value(total_revenue, CURRENCY_UNIT),
        "EPEX-only revenue": format_value(epex_revenue, CURRENCY_UNIT),
        "Imbalance revenue": format_value(imbalance_revenue, CURRENCY_UNIT),
        "Greenchoice benchmark": format_value(greenchoice_revenue, CURRENCY_UNIT),
        "Below-strike revenue": format_value(below_strike_revenue, CURRENCY_UNIT),
        "Avg EPEX price": format_value(avg_epex, PRICE_UNIT),
        "Min EPEX price": format_value(min_epex, PRICE_UNIT),
        "Max EPEX price": format_value(max_epex, PRICE_UNIT),
    }


def build_anomaly_event_tables(df: pd.DataFrame, time_col: str, row_count: int = 10) -> dict[str, dict]:
    if df.empty or time_col not in df.columns:
        return {}

    source = df.copy()
    source[time_col] = pd.to_datetime(source[time_col], errors="coerce")
    source = source.dropna(subset=[time_col]).sort_values(time_col)

    specs = []
    if "is_below_strike" in source.columns:
        specs.append({
            "key": "negative-price-events",
            "label": "Negative price exposure events",
            "description": "Consecutive periods where EPEX is below the configured strike price.",
            "mask": source["is_below_strike"].fillna(False).astype(bool),
            "driver": "Negative EPEX exposure",
            "impact_col": "strike_nomination_revenue",
            "impact_unit": CURRENCY_UNIT,
            "suggested_check": "Review nominated volume and whether curtailment or dispatch action was possible during the price event.",
        })
    if "abs_imbalance_volume_mwh_calc" in source.columns:
        threshold = source["abs_imbalance_volume_mwh_calc"].quantile(0.95)
        threshold = max(threshold, 0)
        specs.append({
            "key": "large-imbalance-events",
            "label": "Large imbalance events",
            "description": "Consecutive periods where absolute imbalance volume is in the top 5% of the selected period.",
            "mask": (source["abs_imbalance_volume_mwh_calc"] > 0) & (source["abs_imbalance_volume_mwh_calc"] >= threshold),
            "driver": "Large delivered-versus-nominated imbalance",
            "impact_col": "imbalance_total_revenue",
            "impact_unit": CURRENCY_UNIT,
            "suggested_check": "Compare nominations against delivered volume and inspect long/short imbalance prices around the event.",
        })
    if "revenue_vs_epex_calc" in source.columns:
        specs.append({
            "key": "revenue-downside-events",
            "label": "Revenue downside events",
            "description": "Consecutive periods where total revenue underperforms EPEX-only revenue.",
            "mask": source["revenue_vs_epex_calc"] < 0,
            "driver": "Actual revenue below EPEX-only revenue",
            "impact_col": "revenue_vs_epex_calc",
            "impact_unit": CURRENCY_UNIT,
            "suggested_check": "Inspect imbalance revenue and capture price drivers for the event window.",
        })
    if "revenue_vs_greenchoice_calc" in source.columns:
        specs.append({
            "key": "benchmark-downside-events",
            "label": "Greenchoice benchmark downside events",
            "description": "Consecutive periods where actual revenue is below the Greenchoice benchmark.",
            "mask": source["revenue_vs_greenchoice_calc"] < 0,
            "driver": "Actual revenue below Greenchoice benchmark",
            "impact_col": "revenue_vs_greenchoice_calc",
            "impact_unit": CURRENCY_UNIT,
            "suggested_check": "Check whether EPEX price, Greenchoice floor, GvO, or imbalance exposure drove the benchmark gap.",
        })

    tables = {}
    for spec in specs:
        records = []
        for group in _event_groups(source, spec["mask"], time_col):
            impact = _sum(group, spec["impact_col"])
            if spec["key"] == "large-imbalance-events":
                impact = _sum(group, "abs_imbalance_volume_mwh_calc")
                impact_unit = "MWh"
            else:
                impact_unit = spec["impact_unit"]
            records.append(_event_record(
                group,
                time_col,
                spec["label"].replace(" events", ""),
                spec["driver"],
                impact,
                impact_unit,
                spec["suggested_check"],
            ))

        table = pd.DataFrame(records)
        if not table.empty:
            severity_order = {"Critical": 0, "High": 1, "Medium": 2, "Review": 3}
            table["_severity_order"] = table["Severity"].map(severity_order).fillna(4)
            table = table.sort_values(["_severity_order", "Start"], ascending=[True, False]).head(row_count)
            table = table.drop(columns=["_severity_order"])

        tables[spec["key"]] = {
            "label": spec["label"],
            "description": spec["description"],
            "rows": table,
        }

    return tables
