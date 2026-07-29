from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import logging
import os
from threading import BoundedSemaphore

from fastapi import APIRouter, Depends, Request, Response

from app_core.metadata import CHART_GROUPS

from ._common import (
    ApiDashboardQuery,
    dashboard_query,
    load_raw_snapshot,
    prepare_snapshot_frames,
)
from .anomalies import build_anomalies_payload
from .bridges import (
    build_revenue_bridge_payload,
    build_strike_exposure_payload,
)
from .monthly import build_monthly_payload
from .quality import build_data_quality_payload
from .scada import build_scada_payload
from .summary import build_summary_payload
from .timeseries import build_timeseries_payload


router = APIRouter()
logger = logging.getLogger(__name__)


def _compute_concurrency() -> int:
    try:
        value = int(os.getenv("DASHBOARD_MAX_CONCURRENT_COMPUTATIONS", "2"))
    except ValueError:
        value = 2
    return max(1, min(value, 8))


_COMPUTE_CONCURRENCY = _compute_concurrency()
_COMPUTE_SLOTS = BoundedSemaphore(_COMPUTE_CONCURRENCY)
_METADATA_KEYS = {
    "dataset",
    "dataset_version",
    "dataset_loaded_at",
    "cache_status",
}


@contextmanager
def _compute_slot():
    # The dashboard is used by a handful of authenticated users. A short queue protects
    # the B1 worker from overlapping dataframe-heavy refreshes without burdening normal use.
    acquired = _COMPUTE_SLOTS.acquire(timeout=5)
    if not acquired:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=429,
            detail="The dashboard is busy. Please retry shortly.",
            headers={"Retry-After": "2"},
        )
    try:
        yield
    finally:
        _COMPUTE_SLOTS.release()


def _response_etag(dataset_etag: str, query: ApiDashboardQuery) -> str:
    payload = {
        "schema": 2,
        "dataset_etag": dataset_etag,
        "settings": asdict(query.settings),
        "row_count": query.row_count,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return f'"{digest}"'


def _without_metadata(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key not in _METADATA_KEYS}


def _settled(name: str, builder) -> dict:
    try:
        return {"status": "fulfilled", "value": _without_metadata(builder())}
    except Exception:
        logger.exception("Optional dashboard section %s failed.", name)
        return {
            "status": "rejected",
            "error": f"The {name} section could not be calculated.",
        }


@router.get("/dashboard")
def get_dashboard(
    request: Request,
    response: Response,
    query: ApiDashboardQuery = Depends(dashboard_query),
):
    blob_name, snapshot, cache_hit = load_raw_snapshot(query)
    response_etag = _response_etag(snapshot.etag, query)
    common_headers = {
        "Cache-Control": "private, no-cache, must-revalidate",
        "ETag": response_etag,
        "X-Dataset-Version": snapshot.etag,
        "X-Dataset-Cache": "hit" if cache_hit else "miss",
    }

    if request.headers.get("if-none-match") == response_etag:
        return Response(status_code=304, headers=common_headers)

    with _compute_slot():
        loaded = prepare_snapshot_frames(query, blob_name, snapshot, cache_hit)
        # Summary is the one required section. If it fails, fail the whole refresh; all
        # remaining sections preserve the frontend's existing best-effort behavior.
        summary = build_summary_payload(query, loaded)
        sections = {
            "summary": {"status": "fulfilled", "value": summary},
            "monthly": _settled(
                "monthly",
                lambda: build_monthly_payload(query, loaded),
            ),
            "revenueBridge": _settled(
                "revenue bridge",
                lambda: build_revenue_bridge_payload(loaded),
            ),
            "strike": _settled(
                "strike exposure",
                lambda: build_strike_exposure_payload(query, loaded),
            ),
            "anomalies": _settled(
                "anomalies",
                lambda: build_anomalies_payload(query, loaded),
            ),
            "quality": _settled(
                "data quality",
                lambda: build_data_quality_payload(query, loaded),
            ),
            "scada": _settled(
                "SCADA",
                lambda: build_scada_payload(query, loaded),
            ),
            "timeseries": [
                {
                    "group": group,
                    **_settled(
                        f"{group} time series",
                        lambda group=group: build_timeseries_payload(
                            query,
                            loaded,
                            group,
                        ),
                    ),
                }
                for group in CHART_GROUPS
            ],
        }

    for key, value in common_headers.items():
        response.headers[key] = value
    return {
        **loaded.metadata,
        "schema_version": 2,
        "sections": sections,
    }
