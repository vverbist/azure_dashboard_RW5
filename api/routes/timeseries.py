from __future__ import annotations

from fastapi import APIRouter, Depends

from app_core.chart_data import timeseries_chart_data

from ._common import (
    ApiDashboardQuery,
    LoadedDashboardFrames,
    dashboard_query,
    load_dashboard_frames,
)

router = APIRouter()


def build_timeseries_payload(
    query: ApiDashboardQuery,
    loaded: LoadedDashboardFrames,
    chart_group: str | None = None,
) -> dict:
    group = chart_group or query.chart_group
    return {
        **loaded.metadata,
        **timeseries_chart_data(
            loaded.selected,
            query.settings.timestamp_col,
            group,
            query.settings.resampling_rule,
        ),
    }


@router.get("/timeseries")
def get_timeseries(query: ApiDashboardQuery = Depends(dashboard_query)):
    return build_timeseries_payload(query, load_dashboard_frames(query))
