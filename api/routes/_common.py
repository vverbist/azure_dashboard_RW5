from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging
import os

import pandas as pd
from fastapi import HTTPException, Query
from fastapi.responses import Response

from app_core.dashboard import DashboardSettings, prepare_dashboard_frames
from app_core.metadata import CHART_GROUPS, RESAMPLING_RULES
from app_core.serialization import to_jsonable
from app_core.storage import (
    DataSnapshot,
    StorageConfigurationError,
    list_dataset_blobs,
    read_dataset_snapshot,
)

# Default Greenchoice afslag as a percentage number (17 == 17%). Keep in sync with the
# frontend control default in frontend/static/dashboard/state.js.
DEFAULT_AFSLAG_PERCENTAGE = 17.0
DEFAULT_MAX_DATE_RANGE_DAYS = 730

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiDashboardQuery:
    dataset: str | None
    settings: DashboardSettings
    row_count: int = 10
    chart_group: str = "Volumes"


@dataclass(frozen=True)
class LoadedDashboardFrames:
    blob_name: str
    snapshot: DataSnapshot
    raw: pd.DataFrame
    selected: pd.DataFrame
    full: pd.DataFrame
    cache_hit: bool

    @property
    def metadata(self) -> dict:
        return {
            "dataset": self.blob_name,
            "dataset_version": self.snapshot.etag,
            "dataset_loaded_at": self.snapshot.loaded_at.isoformat(),
            "cache_status": "hit" if self.cache_hit else "miss",
        }


def _validate_choice(value: str, allowed, name: str) -> None:
    if value not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {name} '{value}'. Allowed values: {sorted(allowed)}.",
        )


def dashboard_query(
    dataset: str | None = Query(default=None, description="Azure Blob CSV name. Defaults to latest exports/*.csv."),
    timestamp_col: str = Query(default="timestamp_Ams"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    resampling_rule: str = Query(default="Original", description="Chart resolution; one of RESAMPLING_RULES."),
    greenchoice_afslag_percentage: float | None = Query(
        default=None,
        ge=0,
        le=100,
        description="Greenchoice discount as a percentage number: 17 = 17%, 0.5 = 0.5%, 100 = 100%.",
    ),
    greenchoice_afslag_pct: float | None = Query(
        default=None,
        ge=0,
        le=100,
        description="Deprecated alias for greenchoice_afslag_percentage; same percentage semantics.",
    ),
    greenchoice_afslag_floor: float = Query(default=10.0, ge=0),
    gvo_value: float = Query(default=0.0, ge=0),
    strike_price: float = Query(default=0.0),
    row_count: int = Query(default=10, ge=1, le=100),
    chart_group: str = Query(default="Volumes"),
) -> ApiDashboardQuery:
    _validate_choice(resampling_rule, RESAMPLING_RULES, "resampling_rule")
    _validate_choice(chart_group, CHART_GROUPS, "chart_group")
    if start_date is not None and end_date is not None:
        if start_date > end_date:
            raise HTTPException(
                status_code=422,
                detail="start_date must be on or before end_date.",
            )
        try:
            max_days = int(
                os.getenv("DASHBOARD_MAX_DATE_RANGE_DAYS", str(DEFAULT_MAX_DATE_RANGE_DAYS))
            )
        except ValueError:
            max_days = DEFAULT_MAX_DATE_RANGE_DAYS
        if (end_date - start_date).days + 1 > max(max_days, 1):
            raise HTTPException(
                status_code=422,
                detail=f"Selected date range exceeds the {max(max_days, 1)} day limit.",
            )
    afslag = greenchoice_afslag_percentage if greenchoice_afslag_percentage is not None else greenchoice_afslag_pct
    if afslag is None:
        afslag = DEFAULT_AFSLAG_PERCENTAGE
    settings = DashboardSettings(
        timestamp_col=timestamp_col,
        start_date=start_date,
        end_date=end_date,
        resampling_rule=resampling_rule,
        greenchoice_afslag_pct=afslag,
        greenchoice_afslag_floor=greenchoice_afslag_floor,
        gvo_value=gvo_value,
        strike_price=strike_price,
    )
    return ApiDashboardQuery(dataset=dataset, settings=settings, row_count=row_count, chart_group=chart_group)


def resolve_dataset(dataset: str | None) -> str:
    try:
        catalog = list_dataset_blobs()
    except StorageConfigurationError as exc:
        logger.exception("Dataset storage is not configured.")
        raise HTTPException(
            status_code=503,
            detail="Dataset storage is not available.",
        ) from exc
    except Exception as exc:
        logger.exception("Could not load the authorized dataset catalog.")
        raise HTTPException(
            status_code=502,
            detail="Could not access the dataset catalog.",
        ) from exc

    if dataset:
        if dataset not in catalog["all"]:
            raise HTTPException(status_code=404, detail="Dataset is not available.")
        return dataset

    exports = catalog["exports"]
    if not exports:
        raise HTTPException(status_code=404, detail="No YTD export files found under exports/.")
    return exports[-1]


def load_raw_snapshot(query: ApiDashboardQuery) -> tuple[str, DataSnapshot, bool]:
    blob_name = resolve_dataset(query.dataset)
    try:
        snapshot, cache_hit = read_dataset_snapshot(blob_name)
        return blob_name, snapshot, cache_hit
    except StorageConfigurationError as exc:
        logger.exception("Dataset storage is not configured.")
        raise HTTPException(
            status_code=503,
            detail="Dataset storage is not available.",
        ) from exc
    except Exception as exc:
        logger.exception("Could not load dataset %s.", blob_name)
        raise HTTPException(
            status_code=502,
            detail="Could not load the requested dataset.",
        ) from exc


def load_raw_dataset(query: ApiDashboardQuery) -> tuple[str, pd.DataFrame]:
    blob_name, snapshot, _cache_hit = load_raw_snapshot(query)
    return blob_name, snapshot.raw


def load_dashboard_frames(query: ApiDashboardQuery) -> LoadedDashboardFrames:
    blob_name, snapshot, cache_hit = load_raw_snapshot(query)
    return prepare_snapshot_frames(query, blob_name, snapshot, cache_hit)


def prepare_snapshot_frames(
    query: ApiDashboardQuery,
    blob_name: str,
    snapshot: DataSnapshot,
    cache_hit: bool,
) -> LoadedDashboardFrames:
    try:
        base = snapshot.base_frame(query.settings.timestamp_col)
        selected, full = prepare_dashboard_frames(
            snapshot.raw,
            query.settings,
            base_df=base,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LoadedDashboardFrames(
        blob_name=blob_name,
        snapshot=snapshot,
        raw=snapshot.raw,
        selected=selected,
        full=full,
        cache_hit=cache_hit,
    )


def load_prepared_frames(
    query: ApiDashboardQuery,
) -> tuple[str, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    loaded = load_dashboard_frames(query)
    return loaded.blob_name, loaded.raw, loaded.selected, loaded.full


def clean_items(items: list[dict]) -> list[dict]:
    return [
        {key: to_jsonable(value) for key, value in item.items()}
        for item in items
    ]


def csv_response(
    df: pd.DataFrame,
    file_name: str,
    index: bool = False,
    *,
    dataset_version: str | None = None,
) -> Response:
    headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}
    if dataset_version:
        headers["X-Dataset-Version"] = dataset_version
    return Response(
        content=df.to_csv(index=index),
        media_type="text/csv",
        headers=headers,
    )

