from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app_core.anomalies import build_anomaly_event_tables, build_anomaly_table
from app_core.benchmarks import add_greenchoice_benchmark, add_strike_price_diagnostic, summarize_strike_price
from app_core.calculations import (
    add_diagnostic_columns,
    calculate_summary_table,
    filter_by_date_range,
    make_variance_table,
    normalize_percentage,
)
from app_core.chart_data import revenue_bridge_components, timeseries_chart_data
from app_core.completeness import frame_completeness, monthly_completeness
from app_core.formatting import format_value
from app_core.dashboard import (
    DashboardSettings,
    build_executive_narrative,
    build_headline_kpis,
    latest_data_date,
    prepare_dashboard_frames,
)
from app_core.metadata import CURRENCY_UNIT
from app_core.monthly import (
    make_monthly_kpi_table,
    make_monthly_numeric_table,
    month_coverage,
    monthly_projection,
)
from app_core.quality import find_missing_periods, make_data_quality_table


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


def test_imbalance_economics_distinguishes_cash_flow_from_gain_loss():
    df = add_diagnostic_columns(sample_df())

    assert df["revenue_vs_epex_calc"].sum() == pytest.approx(0.0)
    assert df["delivered_day_ahead_value_calc"].sum() == pytest.approx(1180.0)
    assert df["imbalance_gain_loss_vs_day_ahead_calc"].sum() == pytest.approx(-60.0)

    variance = make_variance_table(df).set_index("Metric")
    assert variance.loc["Imbalance settlement cash flow", "Value"] == pytest.approx(0.0)
    assert variance.loc["Imbalance gain/loss vs day-ahead", "Value"] == pytest.approx(-60.0)


def test_imbalance_economics_excludes_incomplete_intervals_consistently():
    source = sample_df()
    source.loc[2, "total_revenue"] = np.nan
    df = add_diagnostic_columns(source)

    variance = make_variance_table(df).set_index("Metric")
    assert variance.loc["Imbalance settlement cash flow", "Value"] == pytest.approx(40.0)
    assert variance.loc["Imbalance gain/loss vs day-ahead", "Value"] == pytest.approx(-10.0)


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


def test_anomaly_event_grouping():
    df = pd.DataFrame({
        "timestamp_Ams": pd.to_datetime([
            "2026-01-01 00:00",
            "2026-01-01 00:15",
            "2026-01-01 01:00",
        ]),
        "delivered_volume_mwh": [10.0, 8.0, 11.0],
        "nominated_volume_mwh": [12.0, 10.0, 9.0],
        "epex_eur_per_mwh": [-5.0, -4.0, 55.0],
        "epex_revenue": [-60.0, -40.0, 495.0],
        "imbalance_total_revenue": [-100.0, -100.0, 60.0],
        "total_revenue": [-160.0, -140.0, 555.0],
    })
    df = add_diagnostic_columns(df)
    df = add_greenchoice_benchmark(df, "delivered_volume_mwh", "epex_eur_per_mwh", 0.17, 10.0, 0.0)
    df = add_strike_price_diagnostic(df, "epex_eur_per_mwh", "nominated_volume_mwh", 0.0)

    tables = build_anomaly_event_tables(df, "timestamp_Ams", row_count=10)
    assert list(tables) == [
        "negative-imbalance-revenue-events",
        "positive-imbalance-revenue-events",
        "negative-epex-revenue-events",
    ]
    assert "benchmark-downside-events" not in tables

    events = tables["negative-imbalance-revenue-events"]["rows"]

    assert len(events) == 1
    assert events.iloc[0]["Periods"] == 2
    assert events.iloc[0]["_event_start"] == "2026-01-01T00:00:00"
    assert events.iloc[0]["_event_end"] == "2026-01-01T00:30:00"
    assert events.iloc[0]["Likely driver"] == "Large negative imbalance settlement cash flow"
    assert "lasted 0.50 h" in events.iloc[0]["What happened?"]


def test_monthly_kpi_table_generation():
    df = analysis_df()
    kpi = make_monthly_kpi_table(df, "timestamp_Ams")
    numeric = make_monthly_numeric_table(df, "timestamp_Ams")

    total_revenue_row = kpi[kpi["KPI"] == "Total revenue"].iloc[0]
    assert total_revenue_row["Jan 2026"] == f"{CURRENCY_UNIT}1,210"
    assert total_revenue_row["Feb 2026"] == f"{CURRENCY_UNIT}-90"
    assert total_revenue_row["YTD total"] == f"{CURRENCY_UNIT}1,120"

    epex_row = kpi[kpi["KPI"] == "EPEX-only revenue"].iloc[0]
    assert epex_row["Jan 2026"] == f"{CURRENCY_UNIT}1,170"

    settlement_row = kpi[kpi["KPI"] == "Imbalance settlement cash flow"].iloc[0]
    gain_loss_row = kpi[kpi["KPI"] == "Imbalance gain/loss vs day-ahead"].iloc[0]
    assert settlement_row["Jan 2026"] == f"{CURRENCY_UNIT}40"
    assert gain_loss_row["Jan 2026"] == f"{CURRENCY_UNIT}-10"

    short_volume_row = kpi[kpi["KPI"] == "Imbalance volume short"].iloc[0]
    long_volume_row = kpi[kpi["KPI"] == "Imbalance volume long"].iloc[0]
    assert short_volume_row["Feb 2026"] == "2 MWh"
    assert long_volume_row["Jan 2026"] == "1 MWh"

    below_hours_row = kpi[kpi["KPI"] == "Below-strike hours"].iloc[0]
    assert below_hours_row["Jan 2026"] == "0.00 h"
    assert below_hours_row["Feb 2026"] == "0.25 h"

    assert "Net imbalance volume" not in kpi["KPI"].tolist()
    assert "Greenchoice benchmark" in kpi["KPI"].tolist()
    assert numeric.loc[numeric["Month"] == "2026-01", "Total revenue EUR"].iloc[0] == pytest.approx(1210.0)
    assert numeric.loc[numeric["Month"] == "2026-01", "Total capture price EUR/MWh"].iloc[0] == pytest.approx(1210.0 / 22.0)
    assert numeric.loc[numeric["Month"] == "2026-02", "Imbalance settlement cash flow EUR"].iloc[0] == pytest.approx(-40.0)
    assert numeric.loc[numeric["Month"] == "2026-02", "Imbalance gain/loss vs day-ahead EUR"].iloc[0] == pytest.approx(-50.0)
    assert numeric.loc[numeric["Month"] == "2026-02", "Below-strike hours"].iloc[0] == pytest.approx(0.25)


def test_prepare_dashboard_frames_applies_diagnostics_to_both_frames():
    settings = DashboardSettings(start_date="2026-01-01", end_date="2026-01-31")
    selected, full = prepare_dashboard_frames(sample_df(), settings)

    assert len(selected) == 2  # January rows only
    assert len(full) == 3  # January and February
    for frame in (selected, full):
        assert "imbalance_volume_mwh_calc" in frame.columns
        assert "delivered_day_ahead_value_calc" in frame.columns
        assert "imbalance_gain_loss_vs_day_ahead_calc" in frame.columns
        assert "greenchoice_revenue" in frame.columns
        assert "is_below_strike" in frame.columns


def test_latest_data_date_uses_full_latest_calendar_day():
    assert latest_data_date(sample_df(), "timestamp_Ams") == "2026-02-01"
    assert latest_data_date(pd.DataFrame(), "timestamp_Ams") is None
    assert latest_data_date(pd.DataFrame({"timestamp_Ams": [pd.NaT]}), "timestamp_Ams") is None


def test_build_headline_kpis():
    df = analysis_df()
    summary = calculate_summary_table(df)
    kpis = {kpi["key"]: kpi for kpi in build_headline_kpis(df, summary)}

    assert kpis["total_revenue"]["value"] == pytest.approx(1120.0)
    assert kpis["imbalance_settlement_cash_flow"]["value"] == pytest.approx(0.0)
    assert kpis["imbalance_gain_loss_vs_day_ahead"]["value"] == pytest.approx(-60.0)
    assert kpis["delivered_volume"]["value"] == pytest.approx(30.0)
    assert kpis["nominated_volume"]["value"] == pytest.approx(31.0)


def test_build_executive_narrative():
    df = analysis_df()
    summary = calculate_summary_table(df)
    variance = make_variance_table(df)
    metrics = [bullet["metric"] for bullet in build_executive_narrative(df, summary, variance)]

    assert "total_revenue" in metrics
    assert "imbalance_settlement_cash_flow" in metrics
    assert "imbalance_gain_loss_vs_day_ahead" in metrics


def test_revenue_bridge_components():
    summary = calculate_summary_table(sample_df())
    components = {c["label"]: c for c in revenue_bridge_components(summary)}

    assert components["Total"]["measure"] == "total"
    assert components["Total"]["value"] == pytest.approx(1120.0)
    assert components["EPEX"]["measure"] == "relative"


def test_timeseries_chart_data():
    df = analysis_df()
    payload = timeseries_chart_data(df, "timestamp_Ams", "Volumes", "Original")

    assert payload["group"] == "Volumes"
    names = [series["name"] for series in payload["series"]]
    assert "delivered_volume_mwh" in names
    assert payload["returned_rows"] == len(df)
    assert "rows" not in payload  # series are sufficient for the frontend


def test_timeseries_chart_data_enforces_deterministic_point_budget():
    timestamps = pd.date_range("2026-01-01", periods=10_000, freq="15min")
    df = pd.DataFrame(
        {
            "timestamp_Ams": timestamps,
            "delivered_volume_mwh": np.ones(len(timestamps)),
            "nominated_volume_mwh": np.ones(len(timestamps)),
        }
    )

    first = timeseries_chart_data(
        df,
        "timestamp_Ams",
        "Volumes",
        "Original",
        point_budget=100,
    )
    second = timeseries_chart_data(
        df,
        "timestamp_Ams",
        "Volumes",
        "Original",
        point_budget=100,
    )

    assert first["returned_rows"] <= 100
    assert first["downsampled"] is True
    assert first["applied_resolution"] != "Original"
    assert first["series"] == second["series"]


def test_data_quality_gap_detection():
    df = pd.DataFrame({
        "timestamp_Ams": pd.to_datetime([
            "2026-01-01 00:00",
            "2026-01-01 00:15",
            # 00:30 is missing
            "2026-01-01 00:45",
            "2026-01-01 01:00",
        ]),
        "value": [1.0, 2.0, 3.0, 4.0],
    })

    missing = find_missing_periods(df, "timestamp_Ams")
    assert list(missing) == [pd.Timestamp("2026-01-01 00:30:00")]

    table = make_data_quality_table(df, "timestamp_Ams")
    gap_row = table[table["Check"] == "Missing periods (gaps)"].iloc[0]
    assert gap_row["Result"] == "1"
    assert gap_row["Status"] == "Issue"


def test_data_quality_no_gaps():
    df = pd.DataFrame({
        "timestamp_Ams": pd.to_datetime(["2026-01-01 00:00", "2026-01-01 00:15", "2026-01-01 00:30"]),
        "value": [1.0, 2.0, 3.0],
    })

    assert find_missing_periods(df, "timestamp_Ams").empty

    table = make_data_quality_table(df, "timestamp_Ams")
    gap_row = table[table["Check"] == "Missing periods (gaps)"].iloc[0]
    assert gap_row["Result"] == "0"
    assert gap_row["Status"] == "OK"


def test_all_nan_revenue_aggregates_to_unavailable():
    df = sample_df()
    df["total_revenue"] = np.nan
    df["epex_revenue"] = np.nan

    summary = calculate_summary_table(df)

    assert pd.isna(summary.loc["Revenue", "Total"])
    assert pd.isna(summary.loc["Revenue", "EPEX"])
    assert format_value(summary.loc["Revenue", "Total"], CURRENCY_UNIT) == "-"


def test_empty_selection_produces_no_financial_narrative():
    empty = add_diagnostic_columns(sample_df().iloc[0:0])
    empty = add_greenchoice_benchmark(empty, "delivered_volume_mwh", "epex_eur_per_mwh", 0.17, 10.0, 0.0)
    empty = add_strike_price_diagnostic(empty, "epex_eur_per_mwh", "nominated_volume_mwh", 0.0)

    summary = calculate_summary_table(empty)
    variance = make_variance_table(empty)

    assert pd.isna(summary.loc["Revenue", "Total"])
    assert build_executive_narrative(empty, summary, variance) == []


def test_filter_by_date_range_rejects_inverted_range():
    with pytest.raises(ValueError):
        filter_by_date_range(sample_df(), "timestamp_Ams", "2026-02-01", "2026-01-01")


def test_format_value_normalizes_negative_zero():
    assert format_value(-0.0, CURRENCY_UNIT) == "€0"
    assert format_value(-0.3, CURRENCY_UNIT) == "€0"  # rounds to -0, shown as 0
    assert format_value(-0.001, "MWh", decimals=2) == "0.00 MWh"


def test_percentage_semantics_are_percent_numbers():
    assert normalize_percentage(17) == pytest.approx(0.17)
    assert normalize_percentage(0.5) == pytest.approx(0.005)
    assert normalize_percentage(1) == pytest.approx(0.01)
    assert normalize_percentage(100) == pytest.approx(1.0)
    assert normalize_percentage(None) == pytest.approx(0.17)  # default is 17%


def test_dashboard_settings_normalizes_afslag_percentage():
    assert DashboardSettings(greenchoice_afslag_pct=17).normalized_afslag_pct == pytest.approx(0.17)
    assert DashboardSettings(greenchoice_afslag_pct=0.5).normalized_afslag_pct == pytest.approx(0.005)
    assert DashboardSettings().normalized_afslag_pct == pytest.approx(0.17)


def test_validate_choice_rejects_unknown_values():
    from fastapi import HTTPException

    from api.routes._common import _validate_choice
    from app_core.metadata import RESAMPLING_RULES

    _validate_choice("Original", RESAMPLING_RULES, "resampling_rule")  # valid -> no raise
    with pytest.raises(HTTPException):
        _validate_choice("Nonsense", RESAMPLING_RULES, "resampling_rule")


def test_frame_completeness_flags_missing_source_dates():
    df = pd.DataFrame({
        "timestamp_Ams": pd.to_datetime([
            "2026-01-01 00:00", "2026-01-01 00:15",
            "2026-01-02 00:00", "2026-01-02 00:15",
        ]),
        "epex_eur_per_mwh": [50.0, 60.0, 55.0, 45.0],
        "nominated_volume_mwh": [np.nan, np.nan, 10.0, 12.0],  # 2026-01-01 fully missing
        "delivered_volume_mwh": [9.0, 11.0, 10.0, 12.0],
    })

    result = frame_completeness(df, "timestamp_Ams")
    by_key = {s["key"]: s for s in result["sources"]}

    assert by_key["market"]["status"] == "complete"
    assert by_key["market"]["coverage_pct"] == 100.0
    nomination = by_key["nomination"]
    assert nomination["status"] == "partial"
    assert nomination["missing_intervals"] == 2
    assert nomination["missing_dates"] == ["2026-01-01"]
    assert nomination["coverage_pct"] == 50.0
    assert result["overall_status"] == "partial"


def test_frame_completeness_all_complete():
    df = pd.DataFrame({
        "timestamp_Ams": pd.to_datetime(["2026-01-01 00:00", "2026-01-01 00:15"]),
        "epex_eur_per_mwh": [50.0, 60.0],
        "nominated_volume_mwh": [9.0, 12.0],
        "delivered_volume_mwh": [9.0, 11.0],
    })

    result = frame_completeness(df, "timestamp_Ams")

    assert result["overall_status"] == "complete"
    assert all(source["status"] == "complete" for source in result["sources"])


def test_monthly_completeness_reports_per_month_status():
    df = pd.DataFrame({
        "timestamp_Ams": pd.to_datetime(["2026-01-01 00:00", "2026-02-01 00:00"]),
        "epex_eur_per_mwh": [50.0, 60.0],
        "nominated_volume_mwh": [np.nan, 12.0],  # January nomination missing
        "delivered_volume_mwh": [9.0, 11.0],
    })

    result = monthly_completeness(df, "timestamp_Ams")

    assert result["by_month"]["2026-01"] == "partial"
    assert result["by_month"]["2026-02"] == "complete"
    assert result["overall"]["overall_status"] == "partial"


def test_month_coverage_flags_partial_current_month():
    df = pd.DataFrame({
        "timestamp_Ams": pd.to_datetime([
            "2026-06-01 00:00", "2026-06-30 23:45",  # June fully elapsed
            "2026-07-01 00:00", "2026-07-22 23:45",  # July partial
        ]),
        "delivered_volume_mwh": [1.0, 2.0, 3.0, 4.0],
    })

    cov = month_coverage(df, "timestamp_Ams")

    assert cov["2026-06"]["is_partial"] is False
    assert cov["2026-06"]["label"] == "Jun 2026"
    assert cov["2026-07"]["is_partial"] is True
    assert cov["2026-07"]["days_covered"] == 22
    assert cov["2026-07"]["days_in_month"] == 31
    assert cov["2026-07"]["coverage_through"] == "2026-07-22"


def test_monthly_projection_extrapolates_only_additive_partial_metrics():
    df = pd.DataFrame({
        "timestamp_Ams": pd.to_datetime([
            "2026-06-15 00:00", "2026-06-30 23:45",  # June reaches month end -> complete
            "2026-07-01 00:00", "2026-07-10 23:45",  # July partial: 10 of 31 days
        ]),
        "delivered_volume_mwh": [1.0, 2.0, 3.0, 4.0],
    })

    proj = monthly_projection(df, "timestamp_Ams")

    assert "2026-06" not in proj  # completed month is not projected
    july = proj["2026-07"]
    assert july["days_covered"] == 10
    assert july["days_in_month"] == 31
    assert july["factor"] == pytest.approx(31 / 10)
    assert "Delivered volume MWh" in july["metrics"]
    assert "Total revenue EUR" in july["metrics"]
    assert "Total capture price EUR/MWh" not in july["metrics"]  # rate: never extrapolated


def test_greenchoice_contract_behavior_across_epex_signs():
    from app_core.contracts import OFFICIAL_GREENCHOICE_TERMS

    terms = OFFICIAL_GREENCHOICE_TERMS[0]
    df = pd.DataFrame({
        "delivered_volume_mwh": [10.0, 10.0, 10.0],
        "epex_eur_per_mwh": [100.0, 0.0, -50.0],  # positive, zero, negative EPEX
        "total_revenue": [0.0, 0.0, 0.0],
    })

    out = add_greenchoice_benchmark(
        df,
        "delivered_volume_mwh",
        "epex_eur_per_mwh",
        terms.afslag_pct / 100,  # add_greenchoice_benchmark takes a fraction
        terms.afslag_floor,
        terms.gvo_value,
    )

    # afslag = max(epex * 0.17, floor 10); net = epex - afslag + gvo; billable = max(net, 0)
    assert out["greenchoice_afslag_eur_per_mwh"].tolist() == pytest.approx([17.0, 10.0, 10.0])
    assert out["greenchoice_billable_price_eur_per_mwh"].tolist() == pytest.approx([83.0, 0.0, 0.0])
    assert out["greenchoice_revenue"].tolist() == pytest.approx([830.0, 0.0, 0.0])


def test_commercial_basis_labels_official_vs_scenario():
    from app_core.contracts import commercial_basis

    official = commercial_basis(17.0, 10.0, 0.0)
    assert official["greenchoice"]["basis"] == "Official"
    assert official["greenchoice"]["differences"] == []
    assert official["strike"]["basis"] == "Scenario"

    scenario = commercial_basis(20.0, 10.0, 0.0)
    assert scenario["greenchoice"]["basis"] == "Scenario"
    assert scenario["greenchoice"]["differences"]


def test_shared_core_does_not_import_streamlit():
    for path in Path("app_core").glob("*.py"):
        assert "import streamlit" not in path.read_text(encoding="utf-8")
