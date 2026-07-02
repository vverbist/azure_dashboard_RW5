from __future__ import annotations

from fastapi import APIRouter, Depends

from app_core.benchmarks import summarize_strike_price
from app_core.calculations import calculate_summary_table
from app_core.chart_data import greenchoice_bridge_components, revenue_bridge_components, strike_exposure_data

from ._common import ApiDashboardQuery, dashboard_query, load_prepared_frames

router = APIRouter()


@router.get("/revenue-bridge")
def get_revenue_bridge(query: ApiDashboardQuery = Depends(dashboard_query)):
    blob_name, _raw, df, _full = load_prepared_frames(query)
    summary = calculate_summary_table(df)
    return {"dataset": blob_name, "components": revenue_bridge_components(summary)}


@router.get("/greenchoice-bridge")
def get_greenchoice_bridge(query: ApiDashboardQuery = Depends(dashboard_query)):
    blob_name, _raw, df, _full = load_prepared_frames(query)
    return {"dataset": blob_name, "components": greenchoice_bridge_components(df)}


@router.get("/strike-exposure")
def get_strike_exposure(query: ApiDashboardQuery = Depends(dashboard_query)):
    blob_name, _raw, df, _full = load_prepared_frames(query)
    strike_summary = summarize_strike_price(df)
    return {
        "dataset": blob_name,
        **strike_exposure_data(
            df,
            query.settings.timestamp_col,
            query.settings.epex_price_col,
            query.settings.strike_price,
            strike_summary,
        ),
    }

