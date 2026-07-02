from __future__ import annotations

from fastapi import APIRouter, Depends

from app_core.dashboard import recognized_columns_table, selected_assumptions_table
from app_core.metadata import timestamp_column_options
from app_core.quality import make_data_quality_table
from app_core.serialization import dataframe_records

from ._common import ApiDashboardQuery, dashboard_query, load_prepared_frames

router = APIRouter()


@router.get("/data-quality")
def get_data_quality(query: ApiDashboardQuery = Depends(dashboard_query)):
    blob_name, raw, df, _full = load_prepared_frames(query)
    return {
        "dataset": blob_name,
        "timestamp_columns": timestamp_column_options(raw),
        "data_quality_checks": dataframe_records(make_data_quality_table(df, query.settings.timestamp_col)),
        "selected_assumptions": dataframe_records(selected_assumptions_table(query.settings)),
        "recognized_columns": dataframe_records(recognized_columns_table(df, query.settings.timestamp_col)),
    }

