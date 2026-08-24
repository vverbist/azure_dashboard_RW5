from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


PIPELINE_DIR = Path(__file__).resolve().parents[1] / "pipeline"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

import azure_sync  # noqa: E402


class Logger:
    def __init__(self):
        self.messages: list[str] = []

    def info(self, message):
        self.messages.append(message)


def parquet_bytes(tmp_path: Path, day: date, value: float) -> bytes:
    file = tmp_path / f"source-{day}.parquet"
    pd.DataFrame(
        {
            "timestamp_Ams": [pd.Timestamp(day)],
            "delivered_volume_mwh": [value],
        }
    ).to_parquet(file, index=False)
    return file.read_bytes()


def test_market_daily_blob_parser_rejects_mismatched_year():
    day = date(2026, 8, 23)
    assert azure_sync.market_daily_blob(day) == "daily/2026/2026-08-23.parquet"
    assert azure_sync.day_from_market_blob("daily/2026/2026-08-23.parquet") == day
    assert azure_sync.day_from_market_blob("daily/2025/2026-08-23.parquet") is None
    assert azure_sync.day_from_market_blob("exports/2026_ytd.csv") is None


def test_sync_market_daily_cache_restores_azure_as_authoritative(
    monkeypatch, tmp_path
):
    day = date(2026, 8, 23)
    blob_name = azure_sync.market_daily_blob(day)
    remote_content = parquet_bytes(tmp_path, day, 2.0)

    class Container:
        def create_container(self):
            pass

        def list_blobs(self, name_starts_with):
            assert name_starts_with == "daily/"
            return [SimpleNamespace(name=blob_name)]

        def download_blob(self, requested):
            assert requested == blob_name
            return SimpleNamespace(readall=lambda: remote_content)

    container = Container()
    monkeypatch.setattr(azure_sync, "DAILY_DIR", tmp_path / "daily")
    monkeypatch.setattr(azure_sync, "azure_container_client", lambda: container)

    local_file = azure_sync.market_daily_file(day)
    local_file.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "timestamp_Ams": [pd.Timestamp(day)],
            "delivered_volume_mwh": [1.0],
        }
    ).to_parquet(local_file, index=False)

    restored = azure_sync.sync_market_daily_cache(years={2026}, logger=Logger())

    assert restored == {day}
    assert pd.read_parquet(local_file)["delivered_volume_mwh"].tolist() == [2.0]


def test_upload_market_daily_file_uses_canonical_blob_name(monkeypatch, tmp_path):
    day = date(2026, 8, 23)
    local_file = tmp_path / "day.parquet"
    pd.DataFrame(
        {
            "timestamp_Ams": [pd.Timestamp(day)],
            "delivered_volume_mwh": [1.0],
        }
    ).to_parquet(local_file, index=False)
    uploads: list[tuple[str, bool, bytes]] = []

    class Blob:
        def __init__(self, name):
            self.name = name

        def upload_blob(self, source, *, overwrite, content_settings):
            uploads.append((self.name, overwrite, source.read()))

    class Container:
        def get_blob_client(self, name):
            return Blob(name)

    monkeypatch.setattr(azure_sync, "azure_container_client", lambda: Container())

    azure_sync.upload_market_daily_file(local_file, day, overwrite=False)

    assert uploads == [
        ("daily/2026/2026-08-23.parquet", False, local_file.read_bytes())
    ]


def test_azure_pipeline_lease_is_released(monkeypatch):
    events: list[str] = []

    class Lease:
        def renew(self):
            events.append("renew")

        def release(self):
            events.append("release")

    class LockBlob:
        def upload_blob(self, content, overwrite):
            assert content == b"RW5 pipeline lock"
            assert overwrite is False
            events.append("create")

        def acquire_lease(self, lease_duration):
            assert lease_duration == azure_sync.LEASE_DURATION_SECONDS
            events.append("acquire")
            return Lease()

    class Container:
        def get_blob_client(self, name):
            assert name == azure_sync.PIPELINE_LOCK_BLOB
            return LockBlob()

    monkeypatch.setattr(azure_sync, "azure_container_client", lambda: Container())

    with azure_sync.azure_pipeline_lease():
        azure_sync.assert_pipeline_lease_healthy()
        assert events == ["create", "acquire"]

    assert events == ["create", "acquire", "release"]
