from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app_core.storage import StorageConfigurationError, list_dataset_blobs

router = APIRouter()


@router.get("/datasets")
def get_datasets():
    try:
        datasets = list_dataset_blobs()
    except StorageConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not list datasets: {exc}") from exc
    return {
        "exports": datasets["exports"],
        "monthly": datasets["monthly"],
        "datasets": datasets["all"],
        "default_dataset": datasets["exports"][-1] if datasets["exports"] else (datasets["all"][-1] if datasets["all"] else None),
    }

