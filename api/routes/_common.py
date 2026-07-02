from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
from fastapi import HTTPException, Query
from fastapi.responses import Response

from app_core.dashboard import DashboardSettings, prepare_dashboard_frames
from app_core.serialization import to_jsonable
from app_core.storage import StorageConfigurationError, list_csv_blobs, read_blob_csv


@dataclass(frozen=True)
class ApiDashboardQuery:
    dataset: str | None
    settings: DashboardSettings
    row_count: int = 10
    chart_group: str = "Volumes"


def dashboard_query(
    dataset: str | None = Query(default=None, description="Azure Blob CSV name. Defaults to latest exports/*.csv."),
    timestamp_col: str = Query(default="timestamp_Ams"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    resampling_rule: str = Query(default="Original"),
    greenchoice_afslag_pct: float | None = Query(default=None, description="Greenchoice discount as 0.17 or 17."),
    greenchoice_afslag_percentage: float | None = Query(default=None, description="Alias for greenchoice_afslag_pct."),
    greenchoice_afslag_floor: float = Query(default=10.0),
    gvo_value: float = Query(default=0.0),
    strike_price: float = Query(default=0.0),
    row_count: int = Query(default=10, ge=1, le=100),
    chart_group: str = Query(default="Volumes"),
) -> ApiDashboardQuery:
    afslag = greenchoice_afslag_percentage if greenchoice_afslag_percentage is not None else greenchoice_afslag_pct
    if afslag is None:
        afslag = 0.17
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
    if dataset:
        return dataset
    try:
        exports = list_csv_blobs("exports/")
    except StorageConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not list datasets: {exc}") from exc
    if not exports:
        raise HTTPException(status_code=404, detail="No YTD export files found under exports/.")
    return exports[-1]


def load_raw_dataset(query: ApiDashboardQuery) -> tuple[str, pd.DataFrame]:
    blob_name = resolve_dataset(query.dataset)
    try:
        return blob_name, read_blob_csv(blob_name)
    except StorageConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not read dataset '{blob_name}': {exc}") from exc


def load_prepared_frames(query: ApiDashboardQuery) -> tuple[str, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    blob_name, raw = load_raw_dataset(query)
    try:
        selected, full = prepare_dashboard_frames(raw, query.settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return blob_name, raw, selected, full


def clean_items(items: list[dict]) -> list[dict]:
    return [
        {key: to_jsonable(value) for key, value in item.items()}
        for item in items
    ]


def csv_response(df: pd.DataFrame, file_name: str, index: bool = False) -> Response:
    return Response(
        content=df.to_csv(index=index),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )

