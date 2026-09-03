from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest


PIPELINE_DIR = Path(__file__).resolve().parents[1] / "pipeline"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

import run_daily_update as daily  # noqa: E402
import pipeline_lib as lib  # noqa: E402


class Logger:
    def info(self, _message):
        pass

    def warning(self, _message):
        pass

    def error(self, _message):
        pass


def test_exception_summary_names_empty_errors_and_redacts_tokens():
    class EmptyError(Exception):
        pass

    assert lib.exception_summary(EmptyError()) == "EmptyError"
    summary = lib.exception_summary(
        RuntimeError("request failed: https://example.test?securityToken=secret&x=1")
    )
    assert "secret" not in summary
    assert "securityToken=[REDACTED]&x=1" in summary


def prepare_daily_run(monkeypatch, tmp_path):
    day = date(2026, 8, 23)
    calls: list[object] = []
    local_file = tmp_path / "daily" / "2026" / f"{day}.parquet"
    local_file.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "timestamp_Ams": [pd.Timestamp(day)],
            "delivered_volume_mwh": [1.0],
        }
    ).to_parquet(local_file, index=False)

    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 24)

    monkeypatch.setattr(daily, "date", FakeDate)
    monkeypatch.setattr(daily, "logger", Logger())
    monkeypatch.setattr(
        daily,
        "sync_market_daily_cache",
        lambda **_kwargs: calls.append("sync") or {day},
    )
    monkeypatch.setattr(daily, "determine_sync_window", lambda _today: (day, day))
    monkeypatch.setattr(
        daily,
        "backfill_days",
        lambda *_args, **_kwargs: calls.append("backfill") or [],
    )
    monkeypatch.setattr(
        daily,
        "repair_nan_timestamps_for_period",
        lambda *_args, **_kwargs: (set(), []),
    )
    monkeypatch.setattr(daily, "market_daily_file", lambda _day: local_file)

    monthly_file = tmp_path / "monthly.csv"
    ytd_file = tmp_path / "ytd.csv"
    monthly_file.write_text("monthly", encoding="utf-8")
    ytd_file.write_text("ytd", encoding="utf-8")
    monkeypatch.setattr(
        daily,
        "rebuild_month",
        lambda *_args: calls.append("rebuild_month") or monthly_file,
    )
    monkeypatch.setattr(
        daily,
        "rebuild_ytd",
        lambda *_args: calls.append("rebuild_ytd") or ytd_file,
    )
    monkeypatch.setattr(
        daily,
        "upload_file_to_blob",
        lambda *_args: calls.append("upload_aggregate"),
    )
    return day, local_file, calls


def test_daily_update_syncs_then_publishes_partitions_before_aggregates(
    monkeypatch, tmp_path
):
    day, _local_file, calls = prepare_daily_run(monkeypatch, tmp_path)
    monkeypatch.setattr(
        daily,
        "upload_market_daily_file",
        lambda _file, upload_day: calls.append(("upload_daily", upload_day)),
    )

    daily.run_locked_update()

    assert calls.index("sync") < calls.index("backfill")
    assert calls.index(("upload_daily", day)) < calls.index("rebuild_month")
    assert calls.index(("upload_daily", day)) < calls.index("rebuild_ytd")


def test_daily_update_leaves_aggregates_unchanged_if_partition_upload_fails(
    monkeypatch, tmp_path
):
    _day, _local_file, calls = prepare_daily_run(monkeypatch, tmp_path)

    def fail_upload(*_args):
        raise RuntimeError("upload failed")

    monkeypatch.setattr(daily, "upload_market_daily_file", fail_upload)

    with pytest.raises(SystemExit):
        daily.run_locked_update()

    assert "rebuild_month" not in calls
    assert "rebuild_ytd" not in calls
    assert "upload_aggregate" not in calls


def test_daily_update_publishes_and_aggregates_days_after_a_source_failure(
    monkeypatch, tmp_path
):
    successful_day, _local_file, calls = prepare_daily_run(monkeypatch, tmp_path)
    failed_day = date(2026, 8, 22)
    monkeypatch.setattr(
        daily,
        "determine_sync_window",
        lambda _today: (failed_day, successful_day),
    )
    monkeypatch.setattr(
        daily,
        "backfill_days",
        lambda *_args, **_kwargs: calls.append("backfill") or [],
    )
    monkeypatch.setattr(
        daily,
        "repair_nan_timestamps_for_period",
        lambda *_args, **_kwargs: (set(), [failed_day]),
    )
    monkeypatch.setattr(
        daily,
        "upload_market_daily_file",
        lambda _file, upload_day: calls.append(("upload_daily", upload_day)),
    )

    with pytest.raises(SystemExit) as exc_info:
        daily.run_locked_update()

    assert exc_info.value.code == 1
    assert ("upload_daily", failed_day) not in calls
    assert ("upload_daily", successful_day) in calls
    assert calls.index(("upload_daily", successful_day)) < calls.index("rebuild_month")
    assert "rebuild_ytd" in calls
    assert "upload_aggregate" in calls


def test_daily_update_aggregates_later_days_restored_from_azure(
    monkeypatch, tmp_path
):
    restored_day, _local_file, calls = prepare_daily_run(monkeypatch, tmp_path)
    failed_day = date(2026, 8, 22)
    monkeypatch.setattr(
        daily,
        "determine_sync_window",
        lambda _today: (date(2026, 8, 24), restored_day),
    )
    monkeypatch.setattr(
        daily,
        "repair_nan_timestamps_for_period",
        lambda *_args, **_kwargs: (set(), [failed_day]),
    )
    monkeypatch.setattr(
        daily,
        "upload_market_daily_file",
        lambda _file, upload_day: calls.append(("upload_daily", upload_day)),
    )

    with pytest.raises(SystemExit) as exc_info:
        daily.run_locked_update()

    assert exc_info.value.code == 1
    assert not any(
        isinstance(call, tuple) and call[0] == "upload_daily" for call in calls
    )
    assert "rebuild_month" in calls
    assert "rebuild_ytd" in calls
    assert "upload_aggregate" in calls
