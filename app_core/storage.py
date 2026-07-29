from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
import os
from threading import RLock
from time import monotonic

import pandas as pd
from azure.storage.blob import BlobServiceClient

from .config import get_azure_connection_string, get_azure_container_name


SCADA_FLAG_DTYPES = {
    "scada_available_potential_warning": "boolean",
    "scada_actual_cap_warning": "boolean",
    "scada_setpoint_fallback_applied": "boolean",
    "scada_frozen_signal": "boolean",
}

DEFAULT_CACHE_MAX_SNAPSHOTS = 4
DEFAULT_CACHE_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_CATALOG_TTL_SECONDS = 60


@dataclass
class DataSnapshot:
    """One immutable-by-convention parsed version of an Azure dataset.

    Raw frames and base frames are shared between requests and must not be mutated.
    Scenario-specific calculations copy the base frame before adding columns.
    """

    blob_name: str
    etag: str
    loaded_at: datetime
    raw: pd.DataFrame
    memory_bytes: int
    _base_frames: dict[str, pd.DataFrame] = field(default_factory=dict, repr=False)
    _period_completeness: dict[tuple[str, str, str], dict] = field(
        default_factory=dict,
        repr=False,
    )
    _monthly_completeness: dict[str, dict] = field(default_factory=dict, repr=False)
    _base_lock: RLock = field(default_factory=RLock, repr=False)

    def base_frame(self, timestamp_col: str) -> pd.DataFrame:
        """Return cached timestamp parsing and setting-independent diagnostics."""
        with self._base_lock:
            cached = self._base_frames.get(timestamp_col)
            if cached is not None:
                return cached

            # Local imports keep storage configuration independent from calculation modules.
            from .calculations import add_diagnostic_columns, parse_time_column

            base = add_diagnostic_columns(parse_time_column(self.raw, timestamp_col))
            self._base_frames[timestamp_col] = base
            self.memory_bytes += int(base.memory_usage(index=True, deep=True).sum())
            with _SNAPSHOT_CACHE_LOCK:
                _evict_to_limits()
            return base

    def completeness(
        self,
        timestamp_col: str,
        start_date=None,
        end_date=None,
    ) -> dict:
        """Return cached source completeness for a selected period."""
        key = (timestamp_col, str(start_date or ""), str(end_date or ""))
        with self._base_lock:
            cached = self._period_completeness.get(key)
            if cached is not None:
                return cached

            from .calculations import filter_by_date_range
            from .completeness import frame_completeness

            selected = filter_by_date_range(
                self.base_frame(timestamp_col),
                timestamp_col,
                start_date,
                end_date,
            )
            result = frame_completeness(selected, timestamp_col)
            self._period_completeness[key] = result
            return result

    def completeness_by_month(self, timestamp_col: str) -> dict:
        """Return cached full-dataset and per-month source completeness."""
        with self._base_lock:
            cached = self._monthly_completeness.get(timestamp_col)
            if cached is not None:
                return cached

            from .completeness import monthly_completeness

            result = monthly_completeness(self.base_frame(timestamp_col), timestamp_col)
            self._monthly_completeness[timestamp_col] = result
            return result


# A single lock intentionally covers ETag validation and loading. The B1 deployment has
# very low concurrency; serializing cold loads prevents duplicate multi-megabyte downloads
# and parses without adding a more fragile per-key lock registry.
_SNAPSHOT_CACHE: OrderedDict[str, DataSnapshot] = OrderedDict()
_SNAPSHOT_CACHE_LOCK = RLock()
# Backward-compatible test/debug alias retained for callers that only clear the old cache.
_CSV_CACHE = _SNAPSHOT_CACHE

_CATALOG_CACHE: tuple[float, dict[str, list[str]]] | None = None
_CATALOG_CACHE_LOCK = RLock()


class StorageConfigurationError(RuntimeError):
    pass


def _positive_int_setting(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _blob_etag(container, blob_name: str) -> str | None:
    """Return the current ETag, or None for minimal clients/test doubles."""
    try:
        return container.get_blob_client(blob_name).get_blob_properties().etag
    except (AttributeError, NotImplementedError):
        return None


def _cache_limits() -> tuple[int, int]:
    return (
        _positive_int_setting("DATASET_CACHE_MAX_SNAPSHOTS", DEFAULT_CACHE_MAX_SNAPSHOTS),
        _positive_int_setting("DATASET_CACHE_MAX_BYTES", DEFAULT_CACHE_MAX_BYTES),
    )


def _evict_to_limits() -> None:
    max_snapshots, max_bytes = _cache_limits()
    while _SNAPSHOT_CACHE and (
        len(_SNAPSHOT_CACHE) > max_snapshots
        or sum(snapshot.memory_bytes for snapshot in _SNAPSHOT_CACHE.values()) > max_bytes
    ):
        _SNAPSHOT_CACHE.popitem(last=False)


def clear_storage_caches() -> None:
    """Clear in-process caches. Intended for tests and controlled maintenance."""
    global _CATALOG_CACHE
    with _SNAPSHOT_CACHE_LOCK:
        _SNAPSHOT_CACHE.clear()
    with _CATALOG_CACHE_LOCK:
        _CATALOG_CACHE = None


def cached_dataset_version(blob_name: str) -> str | None:
    with _SNAPSHOT_CACHE_LOCK:
        cached = _SNAPSHOT_CACHE.get(blob_name)
        return cached.etag if cached else None


def cached_dataset_metadata(blob_name: str) -> dict | None:
    with _SNAPSHOT_CACHE_LOCK:
        snapshot = _SNAPSHOT_CACHE.get(blob_name)
        if snapshot is None:
            return None
        return {
            "dataset_version": snapshot.etag,
            "dataset_loaded_at": snapshot.loaded_at.isoformat(),
            "dataset_memory_bytes": snapshot.memory_bytes,
        }


def get_container_client(
    connection_string: str | None = None,
    container_name: str | None = None,
):
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
    container = get_container_client(
        connection_string=connection_string,
        container_name=container_name,
    )
    return sorted(
        blob.name
        for blob in container.list_blobs(name_starts_with=prefix)
        if blob.name.endswith(".csv")
    )


def read_dataset_snapshot(
    blob_name: str,
    connection_string: str | None = None,
    container_name: str | None = None,
) -> tuple[DataSnapshot, bool]:
    """Return a versioned snapshot and whether this call was an in-process cache hit."""
    container = get_container_client(
        connection_string=connection_string,
        container_name=container_name,
    )

    with _SNAPSHOT_CACHE_LOCK:
        etag = _blob_etag(container, blob_name)
        cached = _SNAPSHOT_CACHE.get(blob_name)
        if etag is not None and cached is not None and cached.etag == etag:
            _SNAPSHOT_CACHE.move_to_end(blob_name)
            return cached, True

        # Do not discard the previous snapshot until the replacement has downloaded and
        # parsed successfully. A failed refresh therefore cannot corrupt the cache, but the
        # request still fails visibly instead of silently serving stale financial results.
        blob_bytes = container.download_blob(blob_name).readall()
        frame = pd.read_csv(BytesIO(blob_bytes), dtype=SCADA_FLAG_DTYPES)
        if etag is None:
            # Without a trustworthy version identifier we cannot safely cache the parse.
            uncached = DataSnapshot(
                blob_name=blob_name,
                etag="unversioned",
                loaded_at=datetime.now(UTC),
                raw=frame,
                memory_bytes=int(frame.memory_usage(index=True, deep=True).sum()),
            )
            return uncached, False

        snapshot = DataSnapshot(
            blob_name=blob_name,
            etag=etag,
            loaded_at=datetime.now(UTC),
            raw=frame,
            memory_bytes=int(frame.memory_usage(index=True, deep=True).sum()),
        )
        _SNAPSHOT_CACHE[blob_name] = snapshot
        _SNAPSHOT_CACHE.move_to_end(blob_name)
        _evict_to_limits()
        return snapshot, False


def read_blob_csv(
    blob_name: str,
    connection_string: str | None = None,
    container_name: str | None = None,
) -> pd.DataFrame:
    snapshot, _cache_hit = read_dataset_snapshot(
        blob_name,
        connection_string=connection_string,
        container_name=container_name,
    )
    return snapshot.raw


def list_dataset_blobs(
    connection_string: str | None = None,
    container_name: str | None = None,
    *,
    use_cache: bool = True,
) -> dict[str, list[str]]:
    """Return the authorized dataset catalog, cached briefly to reduce Blob list calls."""
    global _CATALOG_CACHE
    now = monotonic()
    ttl = _positive_int_setting(
        "DATASET_CATALOG_TTL_SECONDS",
        DEFAULT_CATALOG_TTL_SECONDS,
    )

    if use_cache and connection_string is None and container_name is None:
        with _CATALOG_CACHE_LOCK:
            if _CATALOG_CACHE is not None and _CATALOG_CACHE[0] > now:
                cached = _CATALOG_CACHE[1]
                return {key: list(value) for key, value in cached.items()}

    exports = list_csv_blobs(
        "exports/",
        connection_string=connection_string,
        container_name=container_name,
    )
    monthly = list_csv_blobs(
        "monthly/",
        connection_string=connection_string,
        container_name=container_name,
    )
    result = {
        "exports": exports,
        "monthly": monthly,
        "all": sorted(exports + monthly),
    }

    if use_cache and connection_string is None and container_name is None:
        with _CATALOG_CACHE_LOCK:
            _CATALOG_CACHE = (now + ttl, result)
    return {key: list(value) for key, value in result.items()}
