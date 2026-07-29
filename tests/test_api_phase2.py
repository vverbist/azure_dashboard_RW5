from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
from fastapi.testclient import TestClient

from api import main
from api.routes import _common
from api.routes import datasets as datasets_route
from app_core.storage import DataSnapshot


def _source_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp_Ams": [
                "2026-01-01 00:00",
                "2026-01-01 00:15",
                "2026-02-01 00:00",
            ],
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
        }
    )


def _install_snapshot(monkeypatch) -> DataSnapshot:
    raw = _source_frame()
    snapshot = DataSnapshot(
        blob_name="exports/2026_ytd.csv",
        etag='"etag-test"',
        loaded_at=datetime(2026, 7, 29, tzinfo=UTC),
        raw=raw,
        memory_bytes=int(raw.memory_usage(index=True, deep=True).sum()),
    )
    catalog = {
        "exports": ["exports/2026_ytd.csv"],
        "monthly": ["monthly/2026/2026-01.csv"],
        "all": ["exports/2026_ytd.csv", "monthly/2026/2026-01.csv"],
    }
    monkeypatch.setattr(_common, "list_dataset_blobs", lambda: catalog)
    monkeypatch.setattr(datasets_route, "list_dataset_blobs", lambda: catalog)
    monkeypatch.setattr(
        _common,
        "read_dataset_snapshot",
        lambda _blob_name: (snapshot, True),
    )
    monkeypatch.setattr(
        datasets_route,
        "read_dataset_snapshot",
        lambda _blob_name: (snapshot, True),
    )
    return snapshot


def test_dashboard_bundle_has_version_cache_validator_and_security_headers(monkeypatch):
    _install_snapshot(monkeypatch)
    monkeypatch.setattr(main, "REQUIRE_AUTH", False)
    client = TestClient(main.app)

    response = client.get(
        "/api/dashboard",
        params={"dataset": "exports/2026_ytd.csv"},
        headers={"Accept-Encoding": "gzip"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dataset_version"] == '"etag-test"'
    assert body["schema_version"] == 2
    assert body["sections"]["summary"]["status"] == "fulfilled"
    assert len(body["sections"]["timeseries"]) == 3
    assert "rows" not in body["sections"]["timeseries"][0]["value"]
    assert response.headers["x-dataset-version"] == '"etag-test"'
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "style-src 'self' 'unsafe-inline'" in response.headers["content-security-policy"]
    assert "access-control-allow-origin" not in response.headers

    not_modified = client.get(
        "/api/dashboard",
        params={"dataset": "exports/2026_ytd.csv"},
        headers={"If-None-Match": response.headers["etag"]},
    )
    assert not_modified.status_code == 304
    assert not_modified.content == b""


def test_dataset_outside_catalog_is_rejected_before_blob_read(monkeypatch):
    calls = {"reads": 0}
    monkeypatch.setattr(
        _common,
        "list_dataset_blobs",
        lambda: {"exports": [], "monthly": [], "all": []},
    )

    def unexpected_read(_blob_name):
        calls["reads"] += 1
        raise AssertionError("Unauthorized dataset should not be read.")

    monkeypatch.setattr(_common, "read_dataset_snapshot", unexpected_read)
    monkeypatch.setattr(main, "REQUIRE_AUTH", False)
    response = TestClient(main.app).get(
        "/api/dashboard",
        params={"dataset": "private/secret.csv"},
    )

    assert response.status_code == 404
    assert calls["reads"] == 0


def test_dataset_catalog_bootstraps_period_context_without_monthly_request(monkeypatch):
    _install_snapshot(monkeypatch)
    monkeypatch.setattr(main, "REQUIRE_AUTH", False)

    response = TestClient(main.app).get("/api/datasets")

    assert response.status_code == 200
    assert response.json()["default_context"] == {
        "start_date": "2026-01-01",
        "end_date": "2026-02-01",
        "months": ["2026-01", "2026-02"],
    }
    assert response.headers["cache-control"] == "private, max-age=60"


def test_azure_defense_in_depth_protects_api_and_downloads(monkeypatch):
    monkeypatch.setattr(main, "REQUIRE_AUTH", True)
    client = TestClient(main.app)

    assert client.get("/api/me").status_code == 401
    assert client.get("/api/downloads/summary-table").status_code == 401

    signed_in = client.get(
        "/api/me",
        headers={"X-MS-CLIENT-PRINCIPAL-NAME": "victor@example.com"},
    )
    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["email"] == "victor@example.com"


def test_dashboard_rejects_excessive_date_range_before_storage(monkeypatch):
    monkeypatch.setattr(main, "REQUIRE_AUTH", False)
    response = TestClient(main.app).get(
        "/api/dashboard",
        params={"start_date": "2020-01-01", "end_date": "2026-01-01"},
    )

    assert response.status_code == 422
    assert "day limit" in response.json()["detail"]


def test_upstream_catalog_error_is_sanitized(monkeypatch):
    def fail_catalog():
        raise RuntimeError("secret storage endpoint and credentials")

    monkeypatch.setattr(_common, "list_dataset_blobs", fail_catalog)
    monkeypatch.setattr(main, "REQUIRE_AUTH", False)
    response = TestClient(main.app).get("/api/dashboard")

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not access the dataset catalog."
    assert "secret" not in response.text


def test_download_exposes_dataset_version(monkeypatch):
    _install_snapshot(monkeypatch)
    monkeypatch.setattr(main, "REQUIRE_AUTH", False)
    response = TestClient(main.app).get(
        "/api/downloads/summary-table",
        params={"dataset": "exports/2026_ytd.csv"},
    )

    assert response.status_code == 200
    assert response.headers["x-dataset-version"] == '"etag-test"'
    assert response.headers["content-type"].startswith("text/csv")


def test_static_assets_are_self_hosted_and_immutable(monkeypatch):
    monkeypatch.setattr(main, "REQUIRE_AUTH", False)
    client = TestClient(main.app)

    root = client.get("/")
    assert "cdn.plot.ly" not in root.text
    assert "fonts.googleapis.com" not in root.text
    assert "/static/vendor/plotly-strict-2.35.2.min.js" in root.text

    plotly = client.get("/static/vendor/plotly-strict-2.35.2.min.js")
    assert plotly.status_code == 200
    assert "immutable" in plotly.headers["cache-control"]
