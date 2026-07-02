from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app_core.anomalies import build_anomaly_table
from app_core.calculations import calculate_summary_table
from app_core.dashboard import DashboardSettings, prepare_dashboard_frames
from app_core.metadata import ANOMALY_SPECS, TIMESTAMP_COLUMNS
from app_core.monthly import make_monthly_numeric_table


def pick_timestamp_column(df: pd.DataFrame) -> str:
    for col in TIMESTAMP_COLUMNS:
        if col in df.columns:
            return col
    raise ValueError(f"No recognized timestamp column found. Tried: {', '.join(TIMESTAMP_COLUMNS)}")


def validate(csv_path: Path) -> None:
    raw = pd.read_csv(csv_path)
    timestamp_col = pick_timestamp_column(raw)
    settings = DashboardSettings(timestamp_col=timestamp_col)
    selected, full = prepare_dashboard_frames(raw, settings)

    if selected.empty:
        raise AssertionError("Selected dashboard frame is empty.")

    summary = calculate_summary_table(selected)
    monthly = make_monthly_numeric_table(full, timestamp_col)

    total_revenue = summary.loc["Revenue", "Total"]
    source_total_revenue = selected["total_revenue"].sum() if "total_revenue" in selected.columns else None
    if source_total_revenue is not None and abs(total_revenue - source_total_revenue) > 1e-6:
        raise AssertionError("Summary total revenue does not match source total_revenue.")

    if "total_revenue" in selected.columns and {"epex_revenue", "imbalance_total_revenue"}.issubset(selected.columns):
        residual = (selected["total_revenue"] - selected["epex_revenue"] - selected["imbalance_total_revenue"]).abs().sum()
        if residual > 1e-6:
            raise AssertionError(f"Revenue identity residual is too high: {residual}")

    if monthly.empty:
        raise AssertionError("Monthly numeric table is empty.")

    anomaly_spec = ANOMALY_SPECS["revenue-upside"]
    anomaly_table = build_anomaly_table(selected, timestamp_col, anomaly_spec["metric"], n=5, largest=anomaly_spec["largest"])
    if anomaly_table.empty:
        raise AssertionError("Revenue upside anomaly table is empty.")

    print("Shared calculation validation passed.")
    print(f"CSV: {csv_path}")
    print(f"Rows: {len(selected):,}")
    print(f"Timestamp column: {timestamp_col}")
    print(f"Total revenue: {total_revenue:,.2f}")
    print(f"Monthly rows: {len(monthly):,}")
    print(f"Revenue-upside anomalies: {len(anomaly_table):,}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate shared dashboard calculations without Streamlit.")
    parser.add_argument(
        "csv",
        nargs="?",
        default="data/exports/2026_ytd.csv",
        help="Representative CSV to validate. Defaults to data/exports/2026_ytd.csv.",
    )
    args = parser.parse_args()
    validate(Path(args.csv))


if __name__ == "__main__":
    main()
