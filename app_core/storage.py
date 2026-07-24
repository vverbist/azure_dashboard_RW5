from __future__ import annotations

from io import BytesIO
from threading import Lock

import pandas as pd
from azure.storage.blob import BlobServiceClient

from .config import get_azure_connection_string, get_azure_container_name


SCADA_FLAG_DTYPES = {
    "scada_available_potential_warning": "boolean",
    "scada_actual_cap_warning": "boolean",
    "scada_setpoint_fallback_applied": "boolean",
    "scada_frozen_signal": "boolean",
}

# In-process cache of parsed CSVs keyed by blob name -> (etag, DataFrame). The blob is
# re-parsed only when its ETag changes, so a dashboard refresh (~10 requests) downloads and
# parses each dataset once per version instead of once per request. Cached frames are treated
# as read-only by callers (prepare_dashboard_frames copies before mutating).
_CSV_CACHE: dict[str, tuple[str, pd.DataFrame]] = {}
_CSV_CACHE_LOCK = Lock()
_CSV_CACHE_MAX = 4


def _blob_etag(container, blob_name: str) -> str | None:
    """Cheap ETag lookup used to validate the cache. Returns None when unavailable (e.g. a
    test double without get_blob_client), which disables caching for that call."""
    try:
        return container.get_blob_client(blob_name).get_blob_properties().etag
    except Exception:
        return None


def _cache_get(blob_name: str, etag: str) -> pd.DataFrame | None:
    with _CSV_CACHE_LOCK:
        cached = _CSV_CACHE.get(blob_name)
        return cached[1] if cached and cached[0] == etag else None


def _cache_put(blob_name: str, etag: str, df: pd.DataFrame) -> None:
    with _CSV_CACHE_LOCK:
        _CSV_CACHE[blob_name] = (etag, df)
        while len(_CSV_CACHE) > _CSV_CACHE_MAX:
            oldest = next(iter(_CSV_CACHE))
            if oldest == blob_name:
                break
            del _CSV_CACHE[oldest]


def cached_dataset_version(blob_name: str) -> str | None:
    """The ETag of the currently cached parse of a blob, for response traceability."""
    with _CSV_CACHE_LOCK:
        cached = _CSV_CACHE.get(blob_name)
        return cached[0] if cached else None


class StorageConfigurationError(RuntimeError):
    pass


def get_container_client(connection_string: str | None = None, container_name: str | None = None):
    conn_str = connection_string or get_azure_connection_string()
    if not conn_str:
        raise StorageConfigurationError("AZURE_STORAGE_CONNECTION_STRING is not configured.")
    service = BlobServiceClient.from_connection_string(conn_str)
    return service.get_container_client(container_name or get_azure_container_name())


def list_csv_blobs(
    prefix: str,
    connection_string: str | None = None,
    container_name: str | None = None,
) -> list[str]:
    container = get_container_client(connection_string=connection_string, container_name=container_name)
    return sorted(
        blob.name
        for blob in container.list_blobs(name_starts_with=prefix)
        if blob.name.endswith(".csv")
    )


def read_blob_csv(
    blob_name: str,
    connection_string: str | None = None,
    container_name: str | None = None,
) -> pd.DataFrame:
    container = get_container_client(connection_string=connection_string, container_name=container_name)
    etag = _blob_etag(container, blob_name)
    if etag is not None:
        cached = _cache_get(blob_name, etag)
        if cached is not None:
            return cached

    blob_bytes = container.download_blob(blob_name).readall()
    df = pd.read_csv(BytesIO(blob_bytes), dtype=SCADA_FLAG_DTYPES)

    if etag is not None:
        _cache_put(blob_name, etag, df)
    return df


def list_dataset_blobs(connection_string: str | None = None, container_name: str | None = None) -> dict[str, list[str]]:
    exports = list_csv_blobs("exports/", connection_string=connection_string, container_name=container_name)
    monthly = list_csv_blobs("monthly/", connection_string=connection_string, container_name=container_name)
    return {"exports": exports, "monthly": monthly, "all": sorted(exports + monthly)}
