from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app_core.anomalies import build_anomaly_event_tables, build_anomaly_table
from app_core.metadata import ANOMALY_SPECS
from app_core.serialization import dataframe_records

from ._common import ApiDashboardQuery, dashboard_query, load_prepared_frames

router = APIRouter()


def anomaly_source_df(df, anomaly_type: str):
    if anomaly_type == "negative-imbalance-revenue" and "imbalance_total_revenue" in df.columns:
        return df[df["imbalance_total_revenue"] < 0]
    if anomaly_type == "positive-imbalance-revenue" and "imbalance_total_revenue" in df.columns:
        return df[df["imbalance_total_revenue"] > 0]
    if anomaly_type == "negative-epex-revenue" and "epex_revenue" in df.columns:
        return df[df["epex_revenue"] < 0]
    return df


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
