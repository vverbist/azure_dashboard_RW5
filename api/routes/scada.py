from __future__ import annotations

from fastapi import APIRouter, Depends

from app_core.scada import make_scada_envelope_payload, scada_data_available_through

from ._common import (
    ApiDashboardQuery,
    LoadedDashboardFrames,
    dashboard_query,
    load_dashboard_frames,
)


router = APIRouter()


def build_scada_payload(
    query: ApiDashboardQuery,
    loaded: LoadedDashboardFrames,
) -> dict:
    selected, full = loaded.selected, loaded.full
    return {
        **loaded.metadata,
        "data_available_through": scada_data_available_through(
            full, query.settings.timestamp_col
        ),
        "selected_period": make_scada_envelope_payload(
            selected,
            query.settings.timestamp_col,
            query.settings.resampling_rule,
        ),
    }


@router.get("/scada")
def get_scada(query: ApiDashboardQuery = Depends(dashboard_query)):
    return build_scada_payload(query, load_dashboard_frames(query))
