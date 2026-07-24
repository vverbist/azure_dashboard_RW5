from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends

from app_core.benchmarks import summarize_greenchoice, summarize_strike_price
from app_core.calculations import calculate_summary_table, make_variance_table
from app_core.completeness import frame_completeness
from app_core.contracts import commercial_basis
from app_core.storage import cached_dataset_version
from app_core.dashboard import (
    build_executive_narrative,
    build_headline_kpis,
    format_period_label,
    latest_data_date,
    selected_assumptions_table,
)
from app_core.formatting import format_summary_table, format_variance_table
from app_core.serialization import dataframe_records, dataframe_table

from ._common import ApiDashboardQuery, clean_items, dashboard_query, load_prepared_frames

router = APIRouter()


@router.get("/summary")
def get_summary(query: ApiDashboardQuery = Depends(dashboard_query)):
    blob_name, raw, df, full = load_prepared_frames(query)
    summary = calculate_summary_table(df)
    variance = make_variance_table(df)
    greenchoice_summary = summarize_greenchoice(df)
    strike_summary = summarize_strike_price(df)
    settings = query.settings
    basis = commercial_basis(
        settings.greenchoice_afslag_pct,
        settings.greenchoice_afslag_floor,
        settings.gvo_value,
        settings.start_date if isinstance(settings.start_date, date) else None,
    )

    return {
        "dataset": blob_name,
        "dataset_version": cached_dataset_version(blob_name),
        "commercial_basis": basis,
        "context": {
            "period": format_period_label(df, query.settings.timestamp_col),
            "rows": len(df),
            "source_rows": len(raw),
            "granularity": query.settings.resampling_rule,
            "data_available_through": latest_data_date(full, query.settings.timestamp_col),
            "completeness": frame_completeness(df, query.settings.timestamp_col),
        },
        "headline_kpis": clean_items(build_headline_kpis(df, summary)),
        "executive_narrative": build_executive_narrative(df, summary, variance),
        "commercial_breakdown": {
            "numeric": dataframe_table(summary, include_index=True),
            "formatted": dataframe_table(format_summary_table(summary), include_index=True),
        },
        "variance_table": {
            "numeric": dataframe_records(variance),
            "formatted": dataframe_records(format_variance_table(variance)),
        },
        "greenchoice_summary": dataframe_records(greenchoice_summary),
        "strike_summary": dataframe_records(strike_summary),
        "assumptions": dataframe_records(selected_assumptions_table(query.settings)),
    }
