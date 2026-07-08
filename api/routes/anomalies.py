from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app_core.anomalies import anomaly_source_df, build_anomaly_event_tables, build_anomaly_table, event_rows_between
from app_core.metadata import ANOMALY_SPECS
from app_core.serialization import dataframe_records

from ._common import ApiDashboardQuery, dashboard_query, load_prepared_frames

router = APIRouter()


def build_tables(df, time_col: str, row_count: int, anomaly_type: str):
    specs = ANOMALY_SPECS if anomaly_type == "all" else {anomaly_type: ANOMALY_SPECS[anomaly_type]}
    tables = {}
    for key, spec in specs.items():
        source_df = anomaly_source_df(df, key)
        table = build_anomaly_table(source_df, time_col, spec["metric"], row_count, largest=spec["largest"])
        tables[key] = {
            "label": spec["label"],
            "description": spec["description"],
            "rows": dataframe_records(table),
        }
    return tables


def build_event_tables(df, time_col: str, row_count: int):
    tables = build_anomaly_event_tables(df, time_col, row_count)
    return {
        key: {
            "label": table["label"],
            "description": table["description"],
            "rows": dataframe_records(table["rows"]),
        }
        for key, table in tables.items()
    }


@router.get("/anomalies")
def get_anomalies(
    anomaly_type: str = Query(default="all", description=f"One of: all, {', '.join(ANOMALY_SPECS)}"),
    query: ApiDashboardQuery = Depends(dashboard_query),
):
    if anomaly_type != "all" and anomaly_type not in ANOMALY_SPECS:
        raise HTTPException(status_code=400, detail=f"Unknown anomaly_type '{anomaly_type}'.")
    blob_name, _raw, df, _full = load_prepared_frames(query)
    return {
        "dataset": blob_name,
        "anomaly_type": anomaly_type,
        "tables": build_tables(df, query.settings.timestamp_col, query.row_count, anomaly_type),
        "event_tables": build_event_tables(df, query.settings.timestamp_col, query.row_count),
    }


@router.get("/anomalies/event-rows")
def get_anomaly_event_rows(
    start: datetime = Query(..., description="Event window start (inclusive)."),
    end: datetime = Query(..., description="Event window end (exclusive)."),
    query: ApiDashboardQuery = Depends(dashboard_query),
):
    blob_name, _raw, df, _full = load_prepared_frames(query)
    rows = event_rows_between(df, query.settings.timestamp_col, start, end)
    return {
        "dataset": blob_name,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "rows": dataframe_records(rows),
    }
