from __future__ import annotations

import sys
from contextlib import nullcontext
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest


PIPELINE_DIR = Path(__file__).resolve().parents[1] / "pipeline"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

import scada_pipeline as scada  # noqa: E402


def raw_frame_for_day(day: date) -> pd.DataFrame:
    timestamps = scada.expected_timestamps_for_day(day)
    row_count = len(timestamps)
    offsets = list(range(row_count))
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "P": [500.0 + offset for offset in offsets],
            "PavaVWind": [1000.0 + offset for offset in offsets],
            "AbstMaxP": [800.0 + offset for offset in offsets],
            "PSet1": [600.0 + offset for offset in offsets],
            "Vwind": [8.0 + offset / 100 for offset in offsets],
        }
    )


def test_contiguous_day_ranges_groups_gaps():
    assert scada.contiguous_day_ranges(
        [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 4)]
    ) == [
        (date(2026, 7, 1), date(2026, 7, 2)),
        (date(2026, 7, 4), date(2026, 7, 4)),
    ]


@pytest.mark.parametrize(
    ("day", "expected_rows"),
    [
        (date(2026, 3, 29), 92),
        (date(2026, 7, 1), 96),
        (date(2026, 10, 25), 100),
    ],
)
def test_expected_timestamps_follow_amsterdam_dst(day, expected_rows):
    assert len(scada.expected_timestamps_for_day(day)) == expected_rows
    assert scada.validate_raw_day(raw_frame_for_day(day), day) == []


def test_partition_raw_cache_keeps_only_direct_signals(monkeypatch, tmp_path):
    first_day = date(2026, 3, 28)
    last_day = date(2026, 3, 29)
    cache = pd.concat(
        [raw_frame_for_day(first_day), raw_frame_for_day(last_day)],
        ignore_index=True,
    )
    cache["legacy_derived_energy_mwh"] = 123.0
    source = tmp_path / "cache.csv"
    cache.to_csv(source, index=False)
    monkeypatch.setattr(scada, "RAW_SCADA_DIR", tmp_path / "raw")

    imported = scada.partition_raw_cache(source, first_day, last_day)

    assert imported == [first_day, last_day]
    for day in imported:
        partition = pd.read_parquet(scada.raw_scada_file(day))
        assert list(partition.columns) == ["timestamp_utc", *scada.RAW_SIGNAL_COLUMNS]
        assert scada.validate_raw_day(partition, day) == []


def test_process_raw_scada_applies_loss_chain_and_setpoint_fallback():
    timestamps = pd.date_range("2026-07-01T00:00:00Z", periods=2, freq="15min")
    raw = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "P": [500.0, 700.0],
            "PavaVWind": [1000.0, 1000.0],
            "AbstMaxP": [800.0, 800.0],
            "PSet1": [600.0, float("nan")],
            "Vwind": [8.0, 9.0],
        }
    )

    processed = scada.process_raw_scada(raw)

    assert list(raw.columns) == [
        "timestamp_utc",
        "P",
        "PavaVWind",
        "AbstMaxP",
        "PSet1",
        "Vwind",
    ]
    assert processed["scada_effective_power_cap_kw"].tolist() == [600.0, 800.0]
    assert processed["scada_setpoint_fallback_applied"].tolist() == [False, True]

    first = processed.iloc[0]
    assert first["scada_actual_energy_mwh"] == pytest.approx(0.125)
    assert first["scada_technical_loss_mwh"] == pytest.approx(0.05)
    assert first["scada_dispatch_loss_mwh"] == pytest.approx(0.05)
    assert first["scada_underperformance_loss_mwh"] == pytest.approx(0.025)
    assert first["scada_total_loss_mwh"] == pytest.approx(0.125)
    assert first["scada_loss_balance_error_mwh"] == pytest.approx(0.0)

    second = processed.iloc[1]
    assert pd.isna(second["scada_ems_setpoint_kw"])
    assert second["scada_dispatch_loss_mwh"] == pytest.approx(0.0)
    assert second["scada_underperformance_loss_mwh"] == pytest.approx(0.025)


def test_process_raw_scada_records_signal_order_deviations_without_changing_raw():
    raw = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range(
                "2026-07-01T00:00:00Z", periods=1, freq="15min"
            ),
            "P": [900.0],
            "PavaVWind": [700.0],
            "AbstMaxP": [800.0],
            "PSet1": [750.0],
            "Vwind": [8.0],
        }
    )

    processed = scada.process_raw_scada(raw)

    assert processed.loc[0, "scada_available_above_potential_kw"] == 100.0
    assert processed.loc[0, "scada_actual_above_cap_kw"] == 150.0
    assert bool(processed.loc[0, "scada_available_potential_warning"])
    assert bool(processed.loc[0, "scada_actual_cap_warning"])
    assert processed.loc[0, "scada_total_loss_mwh"] == 0.0
    assert raw.loc[0, "PavaVWind"] == 700.0


def test_diagnostic_thresholds_ignore_small_noise_and_detect_persistence():
    raw = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range(
                "2026-07-01T00:00:00Z", periods=3, freq="15min"
            ),
            "P": [801.5, 802.0, 800.0],
            "PavaVWind": [799.7, 799.7, 799.7],
            "AbstMaxP": [800.0, 800.0, 800.0],
            "PSet1": [800.0, 800.0, 800.0],
            "Vwind": [8.0, 8.0, 8.0],
        }
    )

    processed = scada.process_raw_scada(raw)

    assert not processed["scada_available_potential_warning"].any()
    assert processed["scada_actual_cap_warning"].tolist() == [True, True, False]


def test_daily_loss_balance_warning_uses_absolute_and_relative_thresholds():
    processed = scada.process_raw_scada(
        pd.DataFrame(
            {
                "timestamp_utc": pd.date_range(
                    "2026-07-01T00:00:00Z", periods=1, freq="15min"
                ),
                "P": [500.0],
                "PavaVWind": [1000.0],
                "AbstMaxP": [800.0],
                "PSet1": [600.0],
                "Vwind": [8.0],
            }
        )
    )

    summary = scada.scada_quality_summary(processed)

    assert summary["loss_balance_warning_threshold_mwh"] == pytest.approx(0.05)
    assert summary["loss_balance_warning"] is False


def test_frozen_signal_run_preserves_power_but_excludes_derived_analysis():
    raw = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range(
                "2026-07-01T00:00:00Z", periods=6, freq="15min"
            ),
            "P": [-1.0, -1.0, -1.0, -1.0, 500.0, 501.0],
            "PavaVWind": [364.0, 364.0, 364.0, 364.0, 700.0, 701.0],
            "AbstMaxP": [0.0, 0.0, 0.0, 0.0, 650.0, 651.0],
            "PSet1": [4000.0] * 6,
            "Vwind": [3.3, 3.3, 3.3, 3.3, 6.0, 6.1],
        }
    )

    processed = scada.process_raw_scada(raw)

    assert processed["scada_frozen_signal"].tolist() == [
        True,
        True,
        True,
        True,
        False,
        False,
    ]
    assert processed.loc[0, "scada_actual_power_kw"] == -1.0
    assert pd.isna(processed.loc[0, "scada_actual_energy_mwh"])
    assert pd.isna(processed.loc[0, "scada_total_loss_mwh"])
    assert pd.isna(processed.loc[0, "scada_actual_above_cap_kw"])
    assert not bool(processed.loc[0, "scada_actual_cap_warning"])
    assert processed.loc[4, "scada_actual_energy_mwh"] == pytest.approx(0.125)


def test_constant_setpoint_alone_does_not_trigger_frozen_signal():
    raw = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range(
                "2026-07-01T00:00:00Z", periods=4, freq="15min"
            ),
            "P": [100.0, 110.0, 120.0, 130.0],
            "PavaVWind": [200.0, 210.0, 220.0, 230.0],
            "AbstMaxP": [180.0, 190.0, 200.0, 210.0],
            "PSet1": [4000.0] * 4,
            "Vwind": [5.0, 5.1, 5.2, 5.3],
        }
    )

    processed = scada.process_raw_scada(raw)

    assert not processed["scada_frozen_signal"].any()


def test_two_week_update_queries_once_saves_raw_first_and_enriches_market(
    tmp_path, monkeypatch
):
    day = date(2026, 7, 1)
    raw_dir = tmp_path / "scada" / "raw"
    processed_dir = tmp_path / "scada" / "processed"
    daily_dir = tmp_path / "daily"
    monthly_dir = tmp_path / "monthly"
    export_dir = tmp_path / "exports"

    monkeypatch.setattr(scada, "RAW_SCADA_DIR", raw_dir)
    monkeypatch.setattr(scada, "PROCESSED_SCADA_DIR", processed_dir)
    monkeypatch.setattr(scada, "DAILY_DIR", daily_dir)
    monkeypatch.setattr(scada, "LOCK_FILE", tmp_path / ".pipeline.lock")
    monkeypatch.setattr(scada, "azure_pipeline_lease", lambda **_kwargs: nullcontext())
    monkeypatch.setattr(
        scada,
        "sync_market_daily_cache",
        lambda **_kwargs: calls.append("sync_market") or {day},
    )
    monkeypatch.setattr(scada, "restore_raw_from_azure", lambda *_args: False)

    market_file = daily_dir / "2026" / "2026-07-01.parquet"
    market_file.parent.mkdir(parents=True)
    timestamps = scada.expected_timestamps_for_day(day)
    pd.DataFrame(
        {
            "timestamp": timestamps.dt.tz_convert("UTC").dt.tz_localize(None),
            "timestamp_Ams": timestamps
            .dt.tz_convert("Europe/Amsterdam")
            .dt.tz_localize(None),
            "delivered_volume_mwh": [0.12] * len(timestamps),
            "scada_hierarchy_violation": [False] * len(timestamps),
        }
    ).to_parquet(market_file, index=False)

    calls: list[object] = []
    monkeypatch.setattr(scada, "check_influx_connection", lambda: calls.append("health"))

    def fake_fetch(from_date, to_date, measurements):
        calls.append((from_date, to_date, tuple(measurements)))
        return raw_frame_for_day(day)

    monkeypatch.setattr(scada, "fetch_influx_measurements_utc_15min", fake_fetch)
    monkeypatch.setattr(
        scada,
        "fetch_with_retry",
        lambda _label, function, *args: function(*args),
    )

    def fake_upload(local_file, blob_name):
        assert Path(local_file).exists()
        calls.append(("upload", blob_name))

    monkeypatch.setattr(scada, "upload_file_to_blob", fake_upload)
    monkeypatch.setattr(
        scada,
        "upload_market_daily_file",
        lambda local_file, upload_day: calls.append(
            ("upload_market", upload_day, Path(local_file).name)
        ),
    )

    monthly_file = monthly_dir / "2026" / "2026-07.csv"
    ytd_file = export_dir / "2026_ytd.csv"

    def fake_rebuild_month(year, month):
        monthly_file.parent.mkdir(parents=True, exist_ok=True)
        monthly_file.write_text("month", encoding="utf-8")
        calls.append(("rebuild_month", year, month))
        return monthly_file

    def fake_rebuild_ytd(year):
        ytd_file.parent.mkdir(parents=True, exist_ok=True)
        ytd_file.write_text("ytd", encoding="utf-8")
        calls.append(("rebuild_ytd", year))
        return ytd_file

    monkeypatch.setattr(scada, "rebuild_month", fake_rebuild_month)
    monkeypatch.setattr(scada, "rebuild_ytd", fake_rebuild_ytd)

    class Logger:
        def info(self, _message):
            pass

        def warning(self, _message):
            pass

    touched = scada.update_scada_period(day, day, logger=Logger())

    assert touched == {day}
    assert (raw_dir / "2026" / "2026-07-01.parquet").exists()
    assert (processed_dir / "2026" / "2026-07-01.parquet").exists()

    raw_upload_index = calls.index(("upload", "scada/raw/2026/2026-07-01.parquet"))
    processed_upload_index = calls.index(
        ("upload", "scada/processed/2026/2026-07-01.parquet")
    )
    assert raw_upload_index < processed_upload_index
    market_upload_index = calls.index(
        ("upload_market", day, "2026-07-01.parquet")
    )
    rebuild_month_index = calls.index(("rebuild_month", 2026, 7))
    assert processed_upload_index < market_upload_index < rebuild_month_index

    enriched = pd.read_parquet(market_file)
    assert "delivered_volume_mwh" in enriched.columns
    assert "scada_actual_energy_mwh" in enriched.columns
    assert "scada_hierarchy_violation" not in enriched.columns
    expected_actual_mwh = sum(500.0 + offset for offset in range(96)) * 0.25 / 1000
    assert enriched["scada_actual_energy_mwh"].sum() == pytest.approx(
        expected_actual_mwh
    )

    query_calls = [call for call in calls if isinstance(call, tuple) and len(call) == 3 and call[0] == "2026-07-01"]
    assert query_calls == [
        ("2026-07-01", "2026-07-02", tuple(scada.RAW_SIGNAL_COLUMNS))
    ]
