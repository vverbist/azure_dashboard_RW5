from __future__ import annotations

from fastapi import APIRouter, Depends

from app_core.benchmarks import summarize_strike_price
from app_core.calculations import calculate_summary_table
from app_core.chart_data import greenchoice_bridge_components, revenue_bridge_components, strike_exposure_data

from ._common import (
    ApiDashboardQuery,
    LoadedDashboardFrames,
    dashboard_query,
    load_dashboard_frames,
)

router = APIRouter()


def build_revenue_bridge_payload(loaded: LoadedDashboardFrames) -> dict:
    summary = calculate_summary_table(loaded.selected)
    return {
        **loaded.metadata,
        "components": revenue_bridge_components(summary),
    }


def build_greenchoice_bridge_payload(loaded: LoadedDashboardFrames) -> dict:
    return {
        **loaded.metadata,
        "components": greenchoice_bridge_components(loaded.selected),
    }


def build_strike_exposure_payload(
    query: ApiDashboardQuery,
    loaded: LoadedDashboardFrames,
) -> dict:
    strike_summary = summarize_strike_price(loaded.selected)
    return {
        **loaded.metadata,
        **strike_exposure_data(
            loaded.selected,
            query.settings.timestamp_col,
            query.settings.epex_price_col,
            query.settings.strike_price,
            strike_summary,
        ),
    }


@router.get("/revenue-bridge")
def get_revenue_bridge(query: ApiDashboardQuery = Depends(dashboard_query)):
    return build_revenue_bridge_payload(load_dashboard_frames(query))


@router.get("/greenchoice-bridge")
def get_greenchoice_bridge(query: ApiDashboardQuery = Depends(dashboard_query)):
    return build_greenchoice_bridge_payload(load_dashboard_frames(query))


@router.get("/strike-exposure")
def get_strike_exposure(query: ApiDashboardQuery = Depends(dashboard_query)):
    return build_strike_exposure_payload(query, load_dashboard_frames(query))
