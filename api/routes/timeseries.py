from __future__ import annotations

from fastapi import APIRouter, Depends

from app_core.chart_data import timeseries_chart_data

from ._common import ApiDashboardQuery, dashboard_query, load_prepared_frames

router = APIRouter()


@router.get("/timeseries")
def get_timeseries(query: ApiDashboardQuery = Depends(dashboard_query)):
    blob_name, _raw, df, _full = load_prepared_frames(query)
    return {
        "dataset": blob_name,
        **timeseries_chart_data(
            df,
            query.settings.timestamp_col,
            query.chart_group,
            query.settings.resampling_rule,
        ),
    }

