from __future__ import annotations

from fastapi import APIRouter, Depends

from app_core.benchmarks import summarize_greenchoice, summarize_strike_price
from app_core.calculations import calculate_summary_table, make_variance_table
from app_core.dashboard import (
    build_executive_narrative,
    build_headline_kpis,
    format_period_label,
    selected_assumptions_table,
)
from app_core.formatting import format_summary_table, format_variance_table
from app_core.serialization import dataframe_records, dataframe_table

from ._common import ApiDashboardQuery, clean_items, dashboard_query, load_prepared_frames

router = APIRouter()


@router.get("/summary")
def get_summary(query: ApiDashboardQuery = Depends(dashboard_query)):
    blob_name, raw, df, _full = load_prepared_frames(query)
    summary = calculate_summary_table(df)
    variance = make_variance_table(df)
    greenchoice_summary = summarize_greenchoice(df)
    strike_summary = summarize_strike_price(df)

    return {
        "dataset": blob_name,
        "context": {
            "period": format_period_label(df, query.settings.timestamp_col),
            "rows": len(df),
            "source_rows": len(raw),
            "granularity": query.settings.resampling_rule,
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

