from __future__ import annotations

from fastapi import APIRouter, Depends

from app_core.monthly import make_monthly_chart_source, make_monthly_kpi_table, make_monthly_numeric_table
from app_core.serialization import dataframe_records, to_jsonable

from ._common import ApiDashboardQuery, dashboard_query, load_prepared_frames

router = APIRouter()


@router.get("/monthly")
def get_monthly(query: ApiDashboardQuery = Depends(dashboard_query)):
    blob_name, _raw, _df, full = load_prepared_frames(query)
    kpi_table = make_monthly_kpi_table(full, query.settings.timestamp_col)
    numeric = make_monthly_numeric_table(full, query.settings.timestamp_col)
    chart_df = make_monthly_chart_source(full, query.settings.timestamp_col)
    chart_metrics = [c for c in chart_df.columns if c != "Month"] if not chart_df.empty else []
    chart_series = [
        {
            "name": metric,
            "x": [to_jsonable(v) for v in chart_df["Month"]],
            "y": [to_jsonable(v) for v in chart_df[metric]],
        }
        for metric in chart_metrics
    ]
    return {
        "dataset": blob_name,
        "monthly_kpi_table": dataframe_records(kpi_table),
        "numeric_monthly_export": dataframe_records(numeric),
        "chart_data": {
            "rows": dataframe_records(chart_df),
            "metrics": chart_metrics,
            "series": chart_series,
        },
    }

