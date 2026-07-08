from __future__ import annotations

import numpy as np
import pandas as pd

from .formatting import format_value
from .metadata import CURRENCY_UNIT, PRICE_UNIT, existing, infer_unit, pretty_name

PERIODS_PER_HOUR = 4


def anomaly_source_df(df: pd.DataFrame, anomaly_type: str) -> pd.DataFrame:
    """Restrict to the rows a given anomaly type is defined over, e.g. only the
    negative-revenue periods for the negative-imbalance-revenue anomaly."""
    if anomaly_type == "negative-imbalance-revenue" and "imbalance_total_revenue" in df.columns:
        return df[df["imbalance_total_revenue"] < 0]
    if anomaly_type == "positive-imbalance-revenue" and "imbalance_total_revenue" in df.columns:
        return df[df["imbalance_total_revenue"] > 0]
    if anomaly_type == "negative-epex-revenue" and "epex_revenue" in df.columns:
        return df[df["epex_revenue"] < 0]
    return df


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
        if metric == "imbalance_total_revenue":
            direction = "positive" if metric_value >= 0 else "negative"
            parts.append(f"Imbalance revenue is {format_value(metric_value, CURRENCY_UNIT)} ({direction}).")
            if "imbalance_volume_mwh_calc" in row:
                imbalance_direction = "long" if row["imbalance_volume_mwh_calc"] >= 0 else "short"
                parts.append(f"Net imbalance: {format_value(row['imbalance_volume_mwh_calc'], 'MWh')} ({imbalance_direction}).")
        elif metric == "epex_revenue":
            parts.append(f"EPEX revenue is {format_value(metric_value, CURRENCY_UNIT)}.")
            if "nominated_volume_mwh" in row and "epex_eur_per_mwh" in row:
                parts.append(f"Nominated {format_value(row['nominated_volume_mwh'], 'MWh')} at EPEX {format_value(row['epex_eur_per_mwh'], PRICE_UNIT)}.")
        elif metric == "revenue_vs_epex_calc":
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
    avg_epex = _mean(group, "epex_eur_per_mwh")
    min_epex = _min(group, "epex_eur_per_mwh")
    max_epex = _max(group, "epex_eur_per_mwh")
    avg_imbalance_long_price = _mean(group, "imbalance_long_eur_per_mwh")
    avg_imbalance_short_price = _mean(group, "imbalance_short_eur_per_mwh")

    if pd.notna(imbalance) and imbalance < 0 and pd.notna(avg_imbalance_short_price):
        imbalance_price = f"{format_value(avg_imbalance_short_price, PRICE_UNIT)} (short)"
    elif pd.notna(avg_imbalance_long_price):
        imbalance_price = f"{format_value(avg_imbalance_long_price, PRICE_UNIT)} (long)"
    else:
        imbalance_price = "-"

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
        "_event_start": start.isoformat() if pd.notna(start) else None,
        "_event_end": end.isoformat() if pd.notna(end) else None,
        "_impact_value": None if pd.isna(impact_value) else float(impact_value),
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
        "Imbalance price": imbalance_price,
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
    if "imbalance_total_revenue" in source.columns:
        negative_revenue = source.loc[source["imbalance_total_revenue"] < 0, "imbalance_total_revenue"]
        positive_revenue = source.loc[source["imbalance_total_revenue"] > 0, "imbalance_total_revenue"]

        if not negative_revenue.empty:
            negative_threshold = negative_revenue.quantile(0.05)
            specs.append({
                "key": "negative-imbalance-revenue-events",
                "label": "Large negative imbalance revenue events",
                "description": "Consecutive periods with strongly negative imbalance revenue.",
                "mask": source["imbalance_total_revenue"] <= negative_threshold,
                "driver": "Large negative imbalance revenue",
                "impact_col": "imbalance_total_revenue",
                "impact_unit": CURRENCY_UNIT,
                "suggested_check": "Inspect delivered-versus-nominated volume, imbalance direction, and short/long imbalance prices around the event.",
            })

        if not positive_revenue.empty:
            positive_threshold = positive_revenue.quantile(0.95)
            specs.append({
                "key": "positive-imbalance-revenue-events",
                "label": "Large positive imbalance revenue events",
                "description": "Consecutive periods with strongly positive imbalance revenue.",
                "mask": source["imbalance_total_revenue"] >= positive_threshold,
                "driver": "Large positive imbalance revenue",
                "impact_col": "imbalance_total_revenue",
                "impact_unit": CURRENCY_UNIT,
                "suggested_check": "Inspect whether long or short imbalance exposure created upside and whether the pattern is repeatable.",
            })

    if "epex_revenue" in source.columns:
        specs.append({
            "key": "negative-epex-revenue-events",
            "label": "Negative EPEX revenue events",
            "description": "Consecutive periods where nominated EPEX revenue is negative.",
            "mask": source["epex_revenue"] < 0,
            "driver": "Negative nominated EPEX revenue",
            "impact_col": "epex_revenue",
            "impact_unit": CURRENCY_UNIT,
            "suggested_check": "Review nominated volume during negative EPEX revenue periods and whether dispatch or curtailment action was possible.",
        })

    tables = {}
    for spec in specs:
        records = []
        for group in _event_groups(source, spec["mask"], time_col):
            impact = _sum(group, spec["impact_col"])
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


EVENT_ROW_COLUMNS = [
    "delivered_volume_mwh",
    "nominated_volume_mwh",
    "imbalance_volume_mwh_calc",
    "epex_eur_per_mwh",
    "imbalance_long_eur_per_mwh",
    "imbalance_short_eur_per_mwh",
    "epex_revenue",
    "imbalance_total_revenue",
    "total_revenue",
]


def event_rows_between(df: pd.DataFrame, time_col: str, start, end) -> pd.DataFrame:
    """Raw (unaggregated) rows for a single event window, for the Phase 4 detail panel."""
    if df.empty or time_col not in df.columns:
        return pd.DataFrame()

    source = df.copy()
    source[time_col] = pd.to_datetime(source[time_col], errors="coerce")
    start = pd.to_datetime(start)
    end = pd.to_datetime(end)

    window = source[
        (source[time_col] >= start) & (source[time_col] < end)
    ].sort_values(time_col)

    cols = [time_col] + existing(EVENT_ROW_COLUMNS, window)
    renamed = {c: pretty_name(c) for c in cols if c != time_col}
    renamed[time_col] = "Timestamp"
    return window[cols].rename(columns=renamed)
