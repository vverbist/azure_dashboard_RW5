from __future__ import annotations

from io import BytesIO

import pandas as pd

from app_core import storage


class _DownloadedBlob:
    def __init__(self, contents: bytes):
        self.contents = contents

    def readall(self) -> bytes:
        return self.contents


class _Container:
    def __init__(self, contents: bytes):
        self.contents = contents

    def download_blob(self, blob_name: str) -> _DownloadedBlob:
        return _DownloadedBlob(self.contents)


def test_read_blob_csv_uses_nullable_boolean_scada_flags(monkeypatch):
    source = pd.DataFrame(
        {
            "timestamp": ["2026-07-01 00:00", "2026-07-01 00:15", "2026-07-01 00:30"],
            "scada_actual_cap_warning": [True, False, None],
            "scada_frozen_signal": [False, True, None],
        }
    )
    buffer = BytesIO()
    source.to_csv(buffer, index=False)
    monkeypatch.setattr(storage, "get_container_client", lambda **kwargs: _Container(buffer.getvalue()))

    result = storage.read_blob_csv("exports/2026_ytd.csv")

    assert str(result["scada_actual_cap_warning"].dtype) == "boolean"
    assert str(result["scada_frozen_signal"].dtype) == "boolean"
    assert result["scada_actual_cap_warning"].tolist() == [True, False, pd.NA]
    assert result["scada_frozen_signal"].tolist() == [False, True, pd.NA]


def test_read_blob_csv_accepts_exports_without_scada_flags(monkeypatch):
    contents = b"timestamp,value\n2026-01-01,1.5\n"
    monkeypatch.setattr(storage, "get_container_client", lambda **kwargs: _Container(contents))

    result = storage.read_blob_csv("monthly/2026/2026-01.csv")

    assert result.to_dict(orient="records") == [{"timestamp": "2026-01-01", "value": 1.5}]


class _Props:
    def __init__(self, etag: str):
        self.etag = etag


class _BlobClient:
    def __init__(self, container: "_CountingContainer"):
        self.container = container

    def get_blob_properties(self) -> _Props:
        return _Props(self.container.etag)


class _CountingContainer:
    def __init__(self, contents: bytes, etag: str):
        self.contents = contents
        self.etag = etag
        self.downloads = 0

    def get_blob_client(self, blob_name: str) -> _BlobClient:
        return _BlobClient(self)

    def download_blob(self, blob_name: str) -> _DownloadedBlob:
        self.downloads += 1
        return _DownloadedBlob(self.contents)


def test_read_blob_csv_caches_by_etag(monkeypatch):
    storage._CSV_CACHE.clear()
    container = _CountingContainer(b"timestamp,value\n2026-01-01,1.5\n", '"etag-1"')
    monkeypatch.setattr(storage, "get_container_client", lambda **kwargs: container)

    first = storage.read_blob_csv("exports/x.csv")
    second = storage.read_blob_csv("exports/x.csv")

    assert container.downloads == 1  # second call served from cache
    assert first.equals(second)
    assert storage.cached_dataset_version("exports/x.csv") == '"etag-1"'

    container.etag = '"etag-2"'  # a new version invalidates the cache
    storage.read_blob_csv("exports/x.csv")
    assert container.downloads == 2
