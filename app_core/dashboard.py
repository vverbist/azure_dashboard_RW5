from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .benchmarks import add_greenchoice_benchmark, add_strike_price_diagnostic
from .calculations import (
    add_diagnostic_columns,
    calculate_summary_table,
    filter_by_date_range,
    make_variance_table,
    normalize_percentage,
    parse_time_column,
)
from .formatting import format_value
from .metadata import (
    EPEX_PRICE_COL,
    GREENCHOICE_VOLUME_COL,
    NOMINATION_VOLUME_COL,
    numeric_columns,
    pretty_name,
    infer_unit,
    agg_for_col,
)


@dataclass(frozen=True)
class DashboardSettings:
    timestamp_col: str = "timestamp_Ams"
    start_date: date | str | None = None
    end_date: date | str | None = None
    resampling_rule: str = "Original"
    greenchoice_afslag_pct: float = 0.17
    greenchoice_afslag_floor: float = 10.0
    gvo_value: float = 0.0
    strike_price: float = 0.0
    greenchoice_volume_col: str = GREENCHOICE_VOLUME_COL
    epex_price_col: str = EPEX_PRICE_COL
    nomination_volume_col: str = NOMINATION_VOLUME_COL

    @property
    def normalized_afslag_pct(self) -> float:
        return normalize_percentage(self.greenchoice_afslag_pct)


def _with_diagnostics(df: pd.DataFrame, settings: DashboardSettings) -> pd.DataFrame:
    out = add_diagnostic_columns(df)
    out = add_greenchoice_benchmark(
        out,
        settings.greenchoice_volume_col,
        settings.epex_price_col,
        settings.normalized_afslag_pct,
        settings.greenchoice_afslag_floor,
        settings.gvo_value,
    )
    out = add_strike_price_diagnostic(
        out,
        settings.epex_price_col,
        settings.nomination_volume_col,
        settings.strike_price,
    )
    return out


def prepare_dashboard_frames(raw_df: pd.DataFrame, settings: DashboardSettings) -> tuple[pd.DataFrame, pd.DataFrame]:
    parsed = parse_time_column(raw_df, settings.timestamp_col)
    selected = filter_by_date_range(parsed, settings.timestamp_col, settings.start_date, settings.end_date)

    return _with_diagnostics(selected, settings), _with_diagnostics(parsed, settings)


def format_period_label(df: pd.DataFrame, time_col: str) -> str:
    if df.empty:
        return "-"
    start = df[time_col].min().strftime("%Y-%m-%d %H:%M")
    end = df[time_col].max().strftime("%Y-%m-%d %H:%M")
    return f"{start} to {end}"


def latest_data_date(df: pd.DataFrame, time_col: str) -> str | None:
    """Return the calendar date of the latest timestamp in a dataset."""
    if df.empty or time_col not in df.columns:
        return None

    latest = df[time_col].max()
    if pd.isna(latest):
        return None

    return latest.strftime("%Y-%m-%d")


def make_status_label(value, positive_good: bool = True) -> str:
    if pd.isna(value):
        return "No data"
    good = value >= 0 if positive_good else value <= 0
    return "Positive" if good else "Warning"


def make_delta_help(value, positive_text: str, negative_text: str) -> str:
    if pd.isna(value):
        return "Not enough data to calculate this diagnostic."
    return positive_text if value >= 0 else negative_text


def build_executive_narrative(df: pd.DataFrame, summary_table: pd.DataFrame, variance_table: pd.DataFrame) -> list[dict]:
    total_revenue = summary_table.loc["Revenue", "Total"] if "Total" in summary_table.columns else np.nan
    rev_vs_epex_series = variance_table.loc[variance_table["Metric"] == "Revenue vs EPEX", "Value"] if not variance_table.empty else pd.Series(dtype=float)
    rev_vs_epex = rev_vs_epex_series.iloc[0] if len(rev_vs_epex_series) else np.nan
    rev_vs_gc = df["revenue_vs_greenchoice_calc"].sum() if "revenue_vs_greenchoice_calc" in df.columns else np.nan
    strike_rev = df["strike_nomination_revenue"].sum() if "strike_nomination_revenue" in df.columns else np.nan
    below_count = int(df["is_below_strike"].sum()) if "is_below_strike" in df.columns else 0

    bullets = []
    if pd.notna(total_revenue):
        bullets.append({"metric": "total_revenue", "text": f"Total revenue for the selected period is {format_value(total_revenue, '€')}."})
    if pd.notna(rev_vs_epex):
        direction = "above" if rev_vs_epex >= 0 else "below"
        bullets.append({"metric": "revenue_vs_epex", "text": f"Actual revenue is {format_value(abs(rev_vs_epex), '€')} {direction} EPEX nomination revenue."})
    if pd.notna(rev_vs_gc):
        direction = "above" if rev_vs_gc >= 0 else "below"
        bullets.append({"metric": "revenue_vs_greenchoice", "text": f"Actual revenue is {format_value(abs(rev_vs_gc), '€')} {direction} the Greenchoice benchmark."})
    if pd.notna(strike_rev):
        bullets.append({"metric": "strike_nomination_revenue", "text": f"There are {below_count:,} below-strike periods, with nomination revenue of {format_value(strike_rev, '€')} during those periods."})
    return bullets


def build_headline_kpis(df: pd.DataFrame, summary_table: pd.DataFrame) -> list[dict]:
    total_revenue = summary_table.loc["Revenue", "Total"]
    total_capture = summary_table.loc["Capture price", "Total"]
    delivered_volume = summary_table.loc["Volume", "Total"]
    nominated_volume = summary_table.loc["Volume", "EPEX"]
    rev_vs_epex = df["revenue_vs_epex_calc"].sum() if "revenue_vs_epex_calc" in df.columns else np.nan
    rev_vs_greenchoice = df["revenue_vs_greenchoice_calc"].sum() if "revenue_vs_greenchoice_calc" in df.columns else np.nan
    strike_revenue = df["strike_nomination_revenue"].sum() if "strike_nomination_revenue" in df.columns else np.nan
    below_strike_count = int(df["is_below_strike"].sum()) if "is_below_strike" in df.columns else 0

    return [
        {"key": "total_revenue", "label": "Total revenue", "value": total_revenue, "formatted": format_value(total_revenue, "€")},
        {"key": "actual_vs_greenchoice", "label": "Actual vs Greenchoice", "value": rev_vs_greenchoice, "formatted": format_value(rev_vs_greenchoice, "€"), "status": make_status_label(rev_vs_greenchoice)},
        {"key": "actual_vs_epex", "label": "Actual vs EPEX", "value": rev_vs_epex, "formatted": format_value(rev_vs_epex, "€"), "status": make_status_label(rev_vs_epex)},
        {"key": "below_strike_revenue", "label": "Below-strike revenue", "value": strike_revenue, "formatted": format_value(strike_revenue, "€"), "status": f"{below_strike_count:,} periods"},
        {"key": "total_capture", "label": "Total capture", "value": total_capture, "formatted": format_value(total_capture, "€/MWh")},
        {"key": "delivered_volume", "label": "Delivered volume", "value": delivered_volume, "formatted": format_value(delivered_volume, "MWh", decimals=0)},
        {"key": "nominated_volume", "label": "Nominated volume", "value": nominated_volume, "formatted": format_value(nominated_volume, "MWh", decimals=0)},
    ]


def selected_assumptions_table(settings: DashboardSettings) -> pd.DataFrame:
    return pd.DataFrame([
        {"Setting": "Greenchoice volume column", "Value": settings.greenchoice_volume_col},
        {"Setting": "EPEX price column", "Value": settings.epex_price_col},
        {"Setting": "Strike nomination volume column", "Value": settings.nomination_volume_col},
        {"Setting": "Greenchoice afslag", "Value": f"{settings.normalized_afslag_pct:.1%}"},
        {"Setting": "Greenchoice afslag floor", "Value": format_value(settings.greenchoice_afslag_floor, "€/MWh")},
        {"Setting": "GvO", "Value": format_value(settings.gvo_value, "€/MWh")},
        {"Setting": "Strike price", "Value": format_value(settings.strike_price, "€/MWh")},
    ])


def recognized_columns_table(df: pd.DataFrame, time_col: str) -> pd.DataFrame:
    return pd.DataFrame([
        {"Column": c, "Label": pretty_name(c), "Unit": infer_unit(c), "Aggregation": agg_for_col(c)}
        for c in numeric_columns(df, excluded=time_col)
    ])
