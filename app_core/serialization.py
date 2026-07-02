from __future__ import annotations

import math
from datetime import date, datetime

import numpy as np
import pandas as pd


def to_jsonable(value):
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if pd.isna(value):
        return None
    return value


def dataframe_records(df: pd.DataFrame) -> list[dict]:
    return [
        {str(col): to_jsonable(value) for col, value in row.items()}
        for row in df.to_dict(orient="records")
    ]


def dataframe_table(df: pd.DataFrame, include_index: bool = False, index_name: str = "Metric") -> list[dict]:
    table = df.reset_index(names=index_name) if include_index else df
    return dataframe_records(table)

