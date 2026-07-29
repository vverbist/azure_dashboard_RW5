from __future__ import annotations

from fastapi import APIRouter, Depends

from app_core.dashboard import recognized_columns_table, selected_assumptions_table
from app_core.metadata import timestamp_column_options
from app_core.quality import make_data_quality_table
from app_core.serialization import dataframe_records

from ._common import (
    ApiDashboardQuery,
    LoadedDashboardFrames,
    dashboard_query,
    load_dashboard_frames,
)

router = APIRouter()


def build_data_quality_payload(
    query: ApiDashboardQuery,
    loaded: LoadedDashboardFrames,
) -> dict:
    raw, df = loaded.raw, loaded.selected
    return {
        **loaded.metadata,
        "timestamp_columns": timestamp_column_options(raw),
        "data_quality_checks": dataframe_records(make_data_quality_table(df, query.settings.timestamp_col)),
        "selected_assumptions": dataframe_records(selected_assumptions_table(query.settings)),
        "recognized_columns": dataframe_records(recognized_columns_table(df, query.settings.timestamp_col)),
    }


@router.get("/data-quality")
def get_data_quality(query: ApiDashboardQuery = Depends(dashboard_query)):
    return build_data_quality_payload(query, load_dashboard_frames(query))
