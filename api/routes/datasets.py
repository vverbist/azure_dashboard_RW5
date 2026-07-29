from __future__ import annotations

import logging

import pandas as pd
from fastapi import APIRouter, HTTPException, Response

from app_core.storage import (
    StorageConfigurationError,
    list_dataset_blobs,
    read_dataset_snapshot,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/datasets")
def get_datasets(response: Response):
    try:
        datasets = list_dataset_blobs()
    except StorageConfigurationError as exc:
        logger.exception("Dataset storage is not configured.")
        raise HTTPException(
            status_code=503,
            detail="Dataset storage is not available.",
        ) from exc
    except Exception as exc:
        logger.exception("Could not list authorized datasets.")
        raise HTTPException(
            status_code=502,
            detail="Could not access the dataset catalog.",
        ) from exc

    default_dataset = (
        datasets["exports"][-1]
        if datasets["exports"]
        else (datasets["all"][-1] if datasets["all"] else None)
    )
    default_context = None
    dataset_version = None
    if default_dataset:
        try:
            snapshot, _cache_hit = read_dataset_snapshot(default_dataset)
            dataset_version = snapshot.etag
            time_col = "timestamp_Ams"
            base = snapshot.base_frame(time_col)
            timestamps = pd.to_datetime(base[time_col], errors="coerce").dropna()
            if not timestamps.empty:
                default_context = {
                    "start_date": timestamps.min().strftime("%Y-%m-%d"),
                    "end_date": timestamps.max().strftime("%Y-%m-%d"),
                    "months": sorted(
                        timestamps.dt.to_period("M").astype(str).unique().tolist()
                    ),
                }
        except Exception:
            # Context only avoids a second initialization refresh. The normal dashboard
            # endpoint remains authoritative and will surface a load failure if necessary.
            logger.exception("Could not build default dataset context.")

    response.headers["Cache-Control"] = "private, max-age=60"
    return {
        "exports": datasets["exports"],
        "monthly": datasets["monthly"],
        "datasets": datasets["all"],
        "default_dataset": default_dataset,
        "default_dataset_version": dataset_version,
        "default_context": default_context,
    }
