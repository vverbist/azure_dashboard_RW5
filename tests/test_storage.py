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
