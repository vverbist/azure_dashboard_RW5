from __future__ import annotations

from fastapi import APIRouter, Depends

from app_core.scada import make_scada_envelope_payload, scada_data_available_through

from ._common import ApiDashboardQuery, dashboard_query, load_prepared_frames


router = APIRouter()


@router.get("/scada")
def get_scada(query: ApiDashboardQuery = Depends(dashboard_query)):
    blob_name, _raw, selected, full = load_prepared_frames(query)
    return {
        "dataset": blob_name,
        "data_available_through": scada_data_available_through(
            full, query.settings.timestamp_col
        ),
        "selected_period": make_scada_envelope_payload(
            selected,
            query.settings.timestamp_col,
            query.settings.resampling_rule,
        ),
    }
