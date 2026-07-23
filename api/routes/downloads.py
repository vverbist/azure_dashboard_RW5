from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from app_core.anomalies import anomaly_source_df, build_anomaly_table
from app_core.calculations import calculate_summary_table, make_variance_table
from app_core.formatting import format_summary_table, format_variance_table
from app_core.metadata import ANOMALY_SPECS
from app_core.monthly import make_monthly_kpi_table, make_monthly_numeric_table
from app_core.scada import make_scada_monthly_download_table, make_scada_monthly_numeric

from ._common import ApiDashboardQuery, csv_response, dashboard_query, load_prepared_frames

router = APIRouter()


@router.get("/downloads/filtered-data")
def download_filtered_data(query: ApiDashboardQuery = Depends(dashboard_query)):
    _blob_name, _raw, df, _full = load_prepared_frames(query)
    return csv_response(df, "filtered_timeseries.csv")


@router.get("/downloads/summary-table")
def download_summary_table(query: ApiDashboardQuery = Depends(dashboard_query)):
    _blob_name, _raw, df, _full = load_prepared_frames(query)
    summary = calculate_summary_table(df)
    return csv_response(format_summary_table(summary), "summary_table.csv", index=True)


@router.get("/downloads/variance-table")
def download_variance_table(query: ApiDashboardQuery = Depends(dashboard_query)):
    _blob_name, _raw, df, _full = load_prepared_frames(query)
    variance = make_variance_table(df)
    return csv_response(format_variance_table(variance), "variance_table.csv")


@router.get("/downloads/monthly-kpi-overview")
def download_monthly_kpi_overview(query: ApiDashboardQuery = Depends(dashboard_query)):
    _blob_name, _raw, _df, full = load_prepared_frames(query)
    table = make_monthly_kpi_table(full, query.settings.timestamp_col)
    return csv_response(table, "monthly_kpi_overview.csv")


@router.get("/downloads/monthly-numeric")
def download_monthly_numeric(query: ApiDashboardQuery = Depends(dashboard_query)):
    _blob_name, _raw, _df, full = load_prepared_frames(query)
    table = make_monthly_numeric_table(full, query.settings.timestamp_col)
    return csv_response(table, "monthly_kpi_numeric.csv")


@router.get("/downloads/scada-monthly-overview")
def download_scada_monthly_overview(query: ApiDashboardQuery = Depends(dashboard_query)):
    _blob_name, _raw, _df, full = load_prepared_frames(query)
    table = make_scada_monthly_download_table(full, query.settings.timestamp_col)
    return csv_response(table, "scada_monthly_overview.csv")


@router.get("/downloads/scada-monthly-numeric")
def download_scada_monthly_numeric(query: ApiDashboardQuery = Depends(dashboard_query)):
    _blob_name, _raw, _df, full = load_prepared_frames(query)
    table = make_scada_monthly_numeric(full, query.settings.timestamp_col)
    return csv_response(table, "scada_monthly_numeric.csv")


@router.get("/downloads/anomalies/{anomaly_type}")
def download_anomaly_table(anomaly_type: str, query: ApiDashboardQuery = Depends(dashboard_query)):
    if anomaly_type != "all" and anomaly_type not in ANOMALY_SPECS:
        raise HTTPException(status_code=400, detail=f"Unknown anomaly_type '{anomaly_type}'.")

    _blob_name, _raw, df, _full = load_prepared_frames(query)
    if anomaly_type == "all":
        tables = []
        for key, spec in ANOMALY_SPECS.items():
            source_df = anomaly_source_df(df, key)
            table = build_anomaly_table(source_df, query.settings.timestamp_col, spec["metric"], query.row_count, largest=spec["largest"])
            if not table.empty:
                table = table.copy()
                table.insert(0, "Anomaly type", spec["label"])
                tables.append(table)
        combined = pd.concat(tables, ignore_index=True) if tables else pd.DataFrame()
        return csv_response(combined, "anomaly_tables.csv")

    spec = ANOMALY_SPECS[anomaly_type]
    source_df = anomaly_source_df(df, anomaly_type)
    table = build_anomaly_table(source_df, query.settings.timestamp_col, spec["metric"], query.row_count, largest=spec["largest"])
    return csv_response(table, spec["file_name"])
