from __future__ import annotations

import pandas as pd
import pytest

from app_core.scada import (
    calculate_scada_period_numeric,
    make_scada_envelope_payload,
    make_scada_monthly_numeric,
    make_scada_monthly_payload,
    make_scada_monthly_table,
    make_scada_period_table,
    scada_data_available_through,
)


def scada_dashboard_frame() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "timestamp_Ams": pd.to_datetime(
                [
                    "2026-01-01 00:00",
                    "2026-01-01 00:15",
                    "2026-01-01 00:30",
                    "2026-02-01 00:00",
                ]
            ),
            "scada_wind_potential_power_kw": [4000.0, 4000.0, 1000.0, 2000.0],
            "scada_technically_available_power_kw": [3200.0, 3600.0, 900.0, 1800.0],
            "scada_effective_power_cap_kw": [2800.0, 3200.0, 800.0, 1600.0],
            "scada_actual_power_kw": [2400.0, 3400.0, -1.0, 1400.0],
            "scada_wind_speed_mps": [8.0, 10.0, 7.0, 6.0],
            "scada_wind_potential_energy_mwh": [1.0, 1.0, None, 0.5],
            "scada_technically_available_energy_mwh": [0.8, 0.9, None, 0.45],
            "scada_effective_cap_energy_mwh": [0.7, 0.8, None, 0.4],
            "scada_actual_energy_mwh": [0.6, 0.85, None, 0.35],
            "scada_technical_loss_mwh": [0.2, 0.1, None, 0.05],
            "scada_dispatch_loss_mwh": [0.1, 0.1, None, 0.05],
            "scada_underperformance_loss_mwh": [0.1, 0.0, None, 0.05],
            "scada_frozen_signal": [False, False, True, False],
            "delivered_volume_mwh": [0.61, 0.86, 0.5, 0.36],
        }
    )
    return frame


def test_scada_period_is_additive_with_explicit_reconciliation():
    values = calculate_scada_period_numeric(scada_dashboard_frame())

    assert values["Valid SCADA coverage %"] == pytest.approx(75.0)
    assert values["Average wind speed m/s"] == pytest.approx(8.0)
    assert values["Wind potential MWh"] == pytest.approx(2.5)
    assert values["Actual output SCADA MWh"] == pytest.approx(1.8)
    assert values["Total positive loss MWh"] == pytest.approx(0.75)
    assert values["Reconciliation adjustment MWh"] == pytest.approx(-0.05)
    assert (
        values["Actual output SCADA MWh"]
        + values["Total positive loss MWh"]
        + values["Reconciliation adjustment MWh"]
    ) == pytest.approx(values["Wind potential MWh"])


def test_scada_data_available_through_uses_last_valid_interval():
    frame = scada_dashboard_frame()

    assert scada_data_available_through(frame, "timestamp_Ams") == "2026-02-01"
    assert (
        scada_data_available_through(frame.iloc[2:3], "timestamp_Ams") is None
    )


def test_scada_monthly_table_has_months_ytd_wind_and_coverage():
    frame = scada_dashboard_frame()
    numeric = make_scada_monthly_numeric(frame, "timestamp_Ams")
    table = make_scada_monthly_table(frame, "timestamp_Ams")

    assert numeric["Month"].tolist() == ["2026-01", "2026-02", "YTD"]
    assert numeric.loc[0, "Valid SCADA coverage %"] == pytest.approx(200 / 3)
    metric_column = "SCADA metric (% of wind potential)"
    assert table[metric_column].tolist() == [
        "SCADA data coverage",
        "Average wind speed",
        "Wind-potential energy",
        "Technically available energy",
        "Effective-cap energy",
        "Delivered energy",
        "Technical loss",
        "Curtailment / EMS loss",
    ]

    wind_row = table[table[metric_column] == "Average wind speed"].iloc[0]
    assert wind_row["Jan 2026"] == "9.00 m/s"
    assert wind_row["YTD"] == "8.00 m/s"
    coverage_row = table[table[metric_column] == "SCADA data coverage"].iloc[0]
    assert coverage_row["Jan 2026"] == "66.7%"

    potential_row = table[table[metric_column] == "Wind-potential energy"].iloc[0]
    assert potential_row["Jan 2026"] == {
        "primary": "2 MWh",
        "secondary": "100.0%",
    }
    delivered_row = table[table[metric_column] == "Delivered energy"].iloc[0]
    assert delivered_row["YTD"] == {
        "primary": "2 MWh",
        "secondary": "72.0%",
    }


def test_scada_period_table_matches_monthly_display_design():
    table = make_scada_period_table(scada_dashboard_frame())
    metric_column = "SCADA metric (% of wind potential)"

    assert table.columns.tolist() == [metric_column, "Selected period"]
    assert table[metric_column].tolist() == [
        "SCADA data coverage",
        "Average wind speed",
        "Wind-potential energy",
        "Technically available energy",
        "Effective-cap energy",
        "Delivered energy",
        "Technical loss",
        "Curtailment / EMS loss",
    ]
    delivered = table[table[metric_column] == "Delivered energy"].iloc[0]
    assert delivered["Selected period"] == {
        "primary": "2 MWh",
        "secondary": "72.0%",
    }


def test_scada_monthly_payload_retains_hidden_balance_metrics():
    payload = make_scada_monthly_payload(
        scada_dashboard_frame(), "timestamp_Ams"
    )
    numeric = pd.DataFrame(payload["numeric"])

    assert "Underperformance loss MWh" in numeric.columns
    assert "Metered delivered MWh" in numeric.columns
    assert "Total positive loss MWh" in numeric.columns
    assert "Reconciliation adjustment MWh" in numeric.columns
    assert numeric.loc[2, "Underperformance loss MWh"] == pytest.approx(0.15)
    assert numeric.loc[2, "Reconciliation adjustment MWh"] == pytest.approx(-0.05)
    assert payload["chart_rows"][0]["Underperformance loss MWh"] == pytest.approx(
        0.1
    )
    assert payload["chart_rows"][0]["Reconciliation adjustment MWh"] == pytest.approx(
        -0.05
    )


def test_scada_envelope_hides_frozen_values_and_reports_range():
    payload = make_scada_envelope_payload(
        scada_dashboard_frame(), "timestamp_Ams", "Original"
    )

    series = {item["key"]: item for item in payload["series"]}
    assert payload["coverage_pct"] == pytest.approx(75.0)
    assert payload["group"] == "SCADA production envelope"
    assert payload["table"] == make_scada_period_table(
        scada_dashboard_frame()
    ).to_dict(orient="records")
    assert series["actual_output"]["y"] == [2.4, 3.4, None, 1.4]
    assert payload["invalid_ranges"] == [
        {"start": "2026-01-01T00:30:00", "end": "2026-01-01T00:45:00"}
    ]


def test_scada_envelope_resamples_power_as_mean_and_coverage_as_share():
    payload = make_scada_envelope_payload(
        scada_dashboard_frame().iloc[:3], "timestamp_Ams", "h"
    )

    series = {item["key"]: item for item in payload["series"]}
    assert series["wind_potential"]["y"] == [4.0]
    assert payload["point_coverage_pct"] == pytest.approx([200 / 3])
