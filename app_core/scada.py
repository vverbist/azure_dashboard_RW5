from __future__ import annotations

import calendar

import numpy as np
import pandas as pd

from .formatting import format_value
from .serialization import dataframe_records, to_jsonable


SCADA_POWER_COLUMNS = {
    "wind_potential": "scada_wind_potential_power_kw",
    "technically_available": "scada_technically_available_power_kw",
    "effective_cap": "scada_effective_power_cap_kw",
    "actual_output": "scada_actual_power_kw",
}

SCADA_ANALYSIS_COLUMNS = [
    *SCADA_POWER_COLUMNS.values(),
    "scada_wind_speed_mps",
    "scada_wind_potential_energy_mwh",
    "scada_technically_available_energy_mwh",
    "scada_effective_cap_energy_mwh",
    "scada_actual_energy_mwh",
    "scada_technical_loss_mwh",
    "scada_dispatch_loss_mwh",
    "scada_underperformance_loss_mwh",
]

SCADA_MONTHLY_NUMERIC_METRICS = [
    ("Valid SCADA coverage", "Valid SCADA coverage %", "%", 2),
    ("Average wind speed", "Average wind speed m/s", "m/s", 2),
    ("Wind-potential energy", "Wind potential MWh", "MWh", 1),
    ("Technical loss", "Technical loss MWh", "MWh", 1),
    ("Technically available energy", "Technically available MWh", "MWh", 1),
    ("Curtailment / EMS loss", "Curtailment loss MWh", "MWh", 1),
    ("Effective-cap energy", "Effective cap MWh", "MWh", 1),
    ("Underperformance loss", "Underperformance loss MWh", "MWh", 1),
    ("Actual turbine output (SCADA)", "Actual output SCADA MWh", "MWh", 1),
    ("Metered delivered energy (valid intervals)", "Metered delivered MWh", "MWh", 1),
    ("Total positive loss", "Total positive loss MWh", "MWh", 1),
    ("Signal reconciliation adjustment", "Reconciliation adjustment MWh", "MWh", 1),
]

SCADA_MONTHLY_NUMERIC_COLUMNS = [
    metric for _, metric, _, _ in SCADA_MONTHLY_NUMERIC_METRICS
]

SCADA_MONTHLY_DISPLAY_METRICS = [
    ("SCADA data coverage", "Valid SCADA coverage %", "coverage"),
    ("Average wind speed", "Average wind speed m/s", "wind_speed"),
    ("Wind-potential energy", "Wind potential MWh", "energy"),
    ("Technically available energy", "Technically available MWh", "energy"),
    ("Effective-cap energy", "Effective cap MWh", "energy"),
    ("Delivered energy", "Actual output SCADA MWh", "energy"),
    ("Technical loss", "Technical loss MWh", "energy"),
    ("Curtailment / EMS loss", "Curtailment loss MWh", "energy"),
]

SCADA_DISPLAY_METRIC_COLUMN = "SCADA metric (% of wind potential)"


def has_scada_analysis(df: pd.DataFrame) -> bool:
    return all(column in df.columns for column in SCADA_ANALYSIS_COLUMNS)


def _frozen_mask(df: pd.DataFrame) -> pd.Series:
    if "scada_frozen_signal" not in df.columns:
        return pd.Series(False, index=df.index, dtype=bool)
    values = df["scada_frozen_signal"]
    if pd.api.types.is_bool_dtype(values.dtype):
        return values.fillna(False).astype(bool)
    return values.map(
        {True: True, False: False, "True": True, "False": False, 1: True, 0: False}
    ).fillna(False).astype(bool)


def valid_scada_mask(df: pd.DataFrame) -> pd.Series:
    if not has_scada_analysis(df):
        return pd.Series(False, index=df.index, dtype=bool)
    return ~_frozen_mask(df) & df[SCADA_ANALYSIS_COLUMNS].notna().all(axis=1)


def scada_data_available_through(
    period_df: pd.DataFrame, time_col: str
) -> str | None:
    if period_df.empty or time_col not in period_df.columns:
        return None
    valid = valid_scada_mask(period_df)
    timestamps = period_df.loc[valid, time_col].dropna()
    if timestamps.empty:
        return None
    return timestamps.max().date().isoformat()


def _sum_valid(valid: pd.DataFrame, column: str) -> float:
    if column not in valid.columns or valid.empty:
        return np.nan
    return valid[column].sum(min_count=1)


def calculate_scada_period_numeric(period_df: pd.DataFrame) -> dict[str, float]:
    if period_df.empty or not has_scada_analysis(period_df):
        return {metric: np.nan for metric in SCADA_MONTHLY_NUMERIC_COLUMNS}

    mask = valid_scada_mask(period_df)
    valid = period_df.loc[mask]
    potential = _sum_valid(valid, "scada_wind_potential_energy_mwh")
    actual = _sum_valid(valid, "scada_actual_energy_mwh")
    technical = _sum_valid(valid, "scada_technical_loss_mwh")
    curtailed = _sum_valid(valid, "scada_dispatch_loss_mwh")
    underperformance = _sum_valid(valid, "scada_underperformance_loss_mwh")
    component_values = [technical, curtailed, underperformance]
    positive_loss = (
        sum(component_values) if all(pd.notna(value) for value in component_values) else np.nan
    )
    reconciliation = (
        potential - actual - positive_loss
        if all(pd.notna(value) for value in [potential, actual, positive_loss])
        else np.nan
    )

    return {
        "Valid SCADA coverage %": 100 * mask.sum() / len(period_df),
        "Average wind speed m/s": valid["scada_wind_speed_mps"].mean(),
        "Wind potential MWh": potential,
        "Technical loss MWh": technical,
        "Technically available MWh": _sum_valid(
            valid, "scada_technically_available_energy_mwh"
        ),
        "Curtailment loss MWh": curtailed,
        "Effective cap MWh": _sum_valid(valid, "scada_effective_cap_energy_mwh"),
        "Underperformance loss MWh": underperformance,
        "Actual output SCADA MWh": actual,
        "Metered delivered MWh": _sum_valid(valid, "delivered_volume_mwh"),
        "Total positive loss MWh": positive_loss,
        "Reconciliation adjustment MWh": reconciliation,
    }


def make_scada_monthly_numeric(period_df: pd.DataFrame, time_col: str) -> pd.DataFrame:
    if period_df.empty or not has_scada_analysis(period_df):
        return pd.DataFrame(columns=["Month", *SCADA_MONTHLY_NUMERIC_COLUMNS])

    work = period_df.copy()
    work["Month"] = work[time_col].dt.to_period("M").astype(str)
    rows = [
        {"Month": month, **calculate_scada_period_numeric(month_df)}
        for month, month_df in work.groupby("Month", sort=True)
    ]
    rows.append({"Month": "YTD", **calculate_scada_period_numeric(work)})
    return pd.DataFrame(rows, columns=["Month", *SCADA_MONTHLY_NUMERIC_COLUMNS])


def _format_scada_display_value(
    monthly_row: pd.Series, metric: str, display_type: str
) -> str | dict[str, str | None]:
    value = monthly_row[metric]
    if display_type == "coverage":
        return "-" if pd.isna(value) else f"{value:,.1f}%"
    if display_type == "wind_speed":
        return "-" if pd.isna(value) else f"{value:,.2f} m/s"

    primary = format_value(value, "MWh", decimals=0)
    potential = monthly_row["Wind potential MWh"]
    if pd.isna(value):
        secondary = None
    elif metric == "Wind potential MWh":
        secondary = "100.0%"
    elif pd.isna(potential) or potential == 0:
        secondary = None
    else:
        secondary = f"{100 * value / potential:,.1f}%"
    return {"primary": primary, "secondary": secondary}


def _make_scada_display_table(
    periods: list[tuple[str, pd.Series]],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for label, metric, display_type in SCADA_MONTHLY_DISPLAY_METRICS:
        row: dict[str, object] = {SCADA_DISPLAY_METRIC_COLUMN: label}
        for column, period_values in periods:
            row[column] = _format_scada_display_value(
                period_values, metric, display_type
            )
        rows.append(row)
    return pd.DataFrame(rows)


def make_scada_monthly_table(period_df: pd.DataFrame, time_col: str) -> pd.DataFrame:
    numeric = make_scada_monthly_numeric(period_df, time_col)
    if numeric.empty:
        return pd.DataFrame()

    periods: list[tuple[str, pd.Series]] = []
    for _, monthly_row in numeric.iterrows():
        month = monthly_row["Month"]
        column = month
        if month != "YTD":
            period = pd.Period(month, freq="M")
            column = f"{calendar.month_abbr[period.month]} {period.year}"
        periods.append((column, monthly_row))
    return _make_scada_display_table(periods)


def make_scada_period_table(period_df: pd.DataFrame) -> pd.DataFrame:
    if period_df.empty or not has_scada_analysis(period_df):
        return pd.DataFrame()
    values = pd.Series(calculate_scada_period_numeric(period_df))
    return _make_scada_display_table([("Selected period", values)])


def make_scada_monthly_download_table(
    period_df: pd.DataFrame, time_col: str
) -> pd.DataFrame:
    table = make_scada_monthly_table(period_df, time_col)
    if table.empty:
        return table

    flattened = table.copy()
    for column in flattened.columns[1:]:
        flattened[column] = flattened[column].map(
            lambda cell: (
                f"{cell['primary']} — {cell['secondary']}"
                if isinstance(cell, dict) and cell.get("secondary")
                else cell.get("primary", "-")
                if isinstance(cell, dict)
                else cell
            )
        )
    return flattened


def make_scada_monthly_payload(period_df: pd.DataFrame, time_col: str) -> dict:
    numeric = make_scada_monthly_numeric(period_df, time_col)
    chart = numeric[numeric["Month"] != "YTD"].copy() if not numeric.empty else numeric
    return {
        "available": not numeric.empty,
        "table": dataframe_records(make_scada_monthly_table(period_df, time_col)),
        "numeric": dataframe_records(numeric),
        "chart_rows": dataframe_records(chart),
    }


def _resample_envelope(
    frame: pd.DataFrame,
    time_col: str,
    power_columns: list[str],
    valid: pd.Series,
    rule: str,
) -> pd.DataFrame:
    work = frame[[time_col, *power_columns]].copy()
    work.loc[~valid, power_columns] = np.nan
    work["valid_scada_fraction"] = valid.astype(float)
    if rule == "Original":
        return work

    aggregations = {column: "mean" for column in power_columns}
    aggregations["valid_scada_fraction"] = "mean"
    return work.set_index(time_col).resample(rule).agg(aggregations).reset_index()


def _invalid_ranges(
    frame: pd.DataFrame,
    time_col: str,
    valid: pd.Series,
) -> list[dict[str, str]]:
    timestamps = frame.loc[~valid, time_col].sort_values()
    if timestamps.empty:
        return []

    interval = pd.Timedelta(minutes=15)
    groups = timestamps.diff().ne(interval).cumsum()
    ranges = []
    for _, values in timestamps.groupby(groups):
        ranges.append(
            {
                "start": to_jsonable(values.iloc[0]),
                "end": to_jsonable(values.iloc[-1] + interval),
            }
        )
    return ranges


def make_scada_envelope_payload(
    period_df: pd.DataFrame,
    time_col: str,
    rule: str,
) -> dict:
    if period_df.empty or not has_scada_analysis(period_df):
        return {
            "available": False,
            "group": "SCADA production envelope",
            "coverage_pct": None,
            "valid_intervals": 0,
            "total_intervals": len(period_df),
            "series": [],
            "table": [],
            "invalid_ranges": [],
        }

    valid = valid_scada_mask(period_df)
    power_columns = list(SCADA_POWER_COLUMNS.values())
    plot = _resample_envelope(period_df, time_col, power_columns, valid, rule)
    labels = {
        "wind_potential": "Wind potential (AAP)",
        "technically_available": "Technically available",
        "effective_cap": "Effective cap",
        "actual_output": "Actual output (SCADA)",
    }
    series = []
    for key, column in SCADA_POWER_COLUMNS.items():
        series.append(
            {
                "key": key,
                "name": column,
                "label": labels[key],
                "unit": "MW",
                "x": [to_jsonable(value) for value in plot[time_col]],
                "y": [to_jsonable(value / 1000) for value in plot[column]],
            }
        )

    return {
        "available": True,
        "group": "SCADA production envelope",
        "coverage_pct": to_jsonable(100 * valid.sum() / len(period_df)),
        "valid_intervals": int(valid.sum()),
        "total_intervals": len(period_df),
        "table": dataframe_records(make_scada_period_table(period_df)),
        "series": series,
        "point_coverage_pct": [
            to_jsonable(value * 100) for value in plot["valid_scada_fraction"]
        ],
        "invalid_ranges": _invalid_ranges(period_df, time_col, valid),
    }
