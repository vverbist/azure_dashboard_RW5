"""Source-aware completeness metadata (roadmap Phase 0.3).

For a given frame this reports, per data source, how complete the required inputs are:
coverage, first/last/last-complete timestamps, which dates are missing, and how far the
source lags the rest of the dataset. This is *informational* (warn-only): totals are
never suppressed, they are annotated so a gap is visible instead of silent.
"""
from __future__ import annotations

import pandas as pd

from .metadata import existing
from .scada import has_scada_analysis, valid_scada_mask

# (key, label, required columns). A source is reported only if at least one of its
# required columns is present in the schema.
SOURCE_SPECS = [
    ("market", "Market price (EPEX)", ["epex_eur_per_mwh"]),
    ("nomination", "Nomination", ["nominated_volume_mwh"]),
    ("metering", "Metering (delivered)", ["delivered_volume_mwh"]),
    (
        "imbalance",
        "Imbalance",
        ["imbalance_long_eur_per_mwh", "imbalance_short_eur_per_mwh", "imbalance_total_revenue"],
    ),
]


def _status(present: int, total: int) -> str:
    if total == 0 or present == 0:
        return "unavailable"
    if present < total:
        return "partial"
    return "complete"


def _source_record(df: pd.DataFrame, time_col: str, key: str, label: str, present_mask: pd.Series) -> dict:
    total = len(df)
    present = int(present_mask.sum())
    times = pd.to_datetime(df[time_col], errors="coerce")
    valid_times = times.dropna()

    missing_times = times[~present_mask].dropna()
    missing_dates = sorted({t.date().isoformat() for t in missing_times})
    complete_times = times[present_mask].dropna()

    last_overall = valid_times.max() if not valid_times.empty else None
    last_complete = complete_times.max() if not complete_times.empty else None
    stale_days = None
    if last_complete is not None and last_overall is not None:
        stale_days = (last_overall.date() - last_complete.date()).days

    return {
        "key": key,
        "label": label,
        "status": _status(present, total),
        "coverage_pct": round(100 * present / total, 2) if total else None,
        "present_intervals": present,
        "total_intervals": total,
        "missing_intervals": total - present,
        "first": valid_times.min().date().isoformat() if not valid_times.empty else None,
        "last": last_overall.date().isoformat() if last_overall is not None else None,
        "last_complete": last_complete.date().isoformat() if last_complete is not None else None,
        "stale_days": stale_days,
        "missing_dates": missing_dates,
    }


def _overall_status(sources: list[dict]) -> str:
    if not sources:
        return "unavailable"
    if all(source["status"] == "complete" for source in sources):
        return "complete"
    if all(source["status"] == "unavailable" for source in sources):
        return "unavailable"
    return "partial"


def frame_completeness(df: pd.DataFrame, time_col: str) -> dict:
    """Per-source completeness for a single frame (e.g. the selected period)."""
    if df.empty or time_col not in df.columns:
        return {"sources": [], "overall_status": "unavailable"}

    sources: list[dict] = []
    for key, label, cols in SOURCE_SPECS:
        cols_present = existing(cols, df)
        if not cols_present:
            continue
        present_mask = df[cols_present].notna().all(axis=1)
        sources.append(_source_record(df, time_col, key, label, present_mask))

    if has_scada_analysis(df):
        sources.append(_source_record(df, time_col, "scada", "SCADA", valid_scada_mask(df)))

    return {"sources": sources, "overall_status": _overall_status(sources)}


def monthly_completeness(full_df: pd.DataFrame, time_col: str) -> dict:
    """Overall completeness for the full dataset plus a per-month status map."""
    overall = frame_completeness(full_df, time_col)
    by_month: dict[str, str] = {}
    if not full_df.empty and time_col in full_df.columns:
        work = full_df.copy()
        work["_month"] = pd.to_datetime(work[time_col], errors="coerce").dt.to_period("M").astype(str)
        for month, month_df in work.groupby("_month", sort=True):
            if month == "NaT":
                continue
            by_month[month] = frame_completeness(month_df, time_col)["overall_status"]
    return {"overall": overall, "by_month": by_month}
