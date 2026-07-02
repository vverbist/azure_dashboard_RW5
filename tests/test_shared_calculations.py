from pathlib import Path

import pandas as pd
import pytest

from app_core.anomalies import build_anomaly_table
from app_core.benchmarks import add_greenchoice_benchmark, add_strike_price_diagnostic, summarize_strike_price
from app_core.calculations import add_diagnostic_columns, calculate_summary_table
from app_core.monthly import make_monthly_kpi_table, make_monthly_numeric_table


def sample_df():
    return pd.DataFrame({
        "timestamp_Ams": pd.to_datetime(["2026-01-01 00:00", "2026-01-01 00:15", "2026-02-01 00:00"]),
        "delivered_volume_mwh": [10.0, 12.0, 8.0],
        "nominated_volume_mwh": [9.0, 12.0, 10.0],
        "volume_long_mwh": [1.0, 0.0, 0.0],
        "volume_short_mwh": [0.0, 0.0, 2.0],
        "epex_eur_per_mwh": [50.0, 60.0, -5.0],
        "imbalance_long_eur_per_mwh": [40.0, 45.0, 30.0],
        "imbalance_short_eur_per_mwh": [20.0, 25.0, 20.0],
        "epex_revenue": [450.0, 720.0, -50.0],
        "imbalance_long_revenue": [40.0, 0.0, 0.0],
        "imbalance_short_revenue": [0.0, 0.0, -40.0],
        "imbalance_total_revenue": [40.0, 0.0, -40.0],
        "total_revenue": [490.0, 720.0, -90.0],
    })


def analysis_df():
    df = add_diagnostic_columns(sample_df())
    df = add_greenchoice_benchmark(df, "delivered_volume_mwh", "epex_eur_per_mwh", 0.17, 10.0, 0.0)
    return add_strike_price_diagnostic(df, "epex_eur_per_mwh", "nominated_volume_mwh", 0.0)


def test_summary_table_calculation():
    summary = calculate_summary_table(sample_df())

    assert summary.loc["Volume", "Total"] == pytest.approx(30.0)
    assert summary.loc["Volume", "EPEX"] == pytest.approx(31.0)
    assert summary.loc["Revenue", "Total"] == pytest.approx(1120.0)
    assert summary.loc["Revenue", "Imbalance long"] == pytest.approx(40.0)
    assert summary.loc["Revenue", "Imbalance short"] == pytest.approx(-40.0)
    assert summary.loc["Capture price", "Total"] == pytest.approx(1120.0 / 30.0)


def test_greenchoice_benchmark_calculation():
    df = add_greenchoice_benchmark(sample_df(), "delivered_volume_mwh", "epex_eur_per_mwh", 0.17, 10.0, 0.0)

    assert df["greenchoice_afslag_eur_per_mwh"].tolist() == pytest.approx([10.0, 10.2, 10.0])
    assert df["greenchoice_billable_price_eur_per_mwh"].tolist() == pytest.approx([40.0, 49.8, 0.0])
    assert df["greenchoice_revenue"].sum() == pytest.approx(997.6)
    assert df["revenue_vs_greenchoice_calc"].sum() == pytest.approx(122.4)


def test_strike_price_diagnostic():
    df = add_strike_price_diagnostic(sample_df(), "epex_eur_per_mwh", "nominated_volume_mwh", 0.0)
    summary = summarize_strike_price(df)

    assert df["is_below_strike"].tolist() == [False, False, True]
    assert df["strike_nomination_revenue"].sum() == pytest.approx(-50.0)
    assert summary.loc[summary["Metric"] == "Periods below strike", "Value"].iloc[0] == 1


def test_anomaly_table_generation():
    table = build_anomaly_table(analysis_df(), "timestamp_Ams", "revenue_vs_epex_calc", n=1, largest=True)

    assert len(table) == 1
    assert "Where is the anomaly?" in table.columns
    assert "above EPEX revenue" in table["Where is the anomaly?"].iloc[0]


def test_monthly_kpi_table_generation():
    df = analysis_df()
    kpi = make_monthly_kpi_table(df, "timestamp_Ams")
    numeric = make_monthly_numeric_table(df, "timestamp_Ams")

    total_revenue_row = kpi[kpi["KPI"] == "Total revenue"].iloc[0]
    assert total_revenue_row["Jan 2026"] == "€1,210"
    assert total_revenue_row["Feb 2026"] == "€-90"
    assert total_revenue_row["YTD total"] == "€1,120"
    assert numeric.loc[numeric["Month"] == "2026-01", "Total revenue EUR"].iloc[0] == pytest.approx(1210.0)


def test_shared_core_does_not_import_streamlit():
    for path in Path("app_core").glob("*.py"):
        assert "import streamlit" not in path.read_text(encoding="utf-8")

