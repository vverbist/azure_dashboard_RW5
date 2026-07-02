from __future__ import annotations

import numpy as np
import pandas as pd


def make_data_quality_table(df: pd.DataFrame, time_col: str) -> pd.DataFrame:
    checks = []
    checks.append({"Check": "Rows loaded", "Result": len(df), "Status": "OK" if len(df) > 0 else "Issue"})
    checks.append({"Check": "Duplicate timestamps", "Result": int(df[time_col].duplicated().sum()), "Status": "Issue" if df[time_col].duplicated().any() else "OK"})
    numeric_missing = int(df.select_dtypes(include=[np.number]).isna().sum().sum())
    checks.append({"Check": "Missing numeric values", "Result": numeric_missing, "Status": "Review" if numeric_missing else "OK"})
    if len(df) > 1:
        median_step = df[time_col].sort_values().diff().median()
        checks.append({"Check": "Median timestamp step", "Result": str(median_step), "Status": "OK"})
    if {"total_revenue", "epex_revenue", "imbalance_total_revenue"}.issubset(df.columns):
        diff = (df["total_revenue"] - df["epex_revenue"] - df["imbalance_total_revenue"]).abs().sum()
        checks.append({"Check": "Revenue identity residual", "Result": f"€{diff:,.2f}", "Status": "Review" if diff > 1e-6 else "OK"})

    q = pd.DataFrame(checks)
    q["Check"] = q["Check"].astype(str)
    q["Result"] = q["Result"].astype(str)
    q["Status"] = q["Status"].astype(str)
    return q

