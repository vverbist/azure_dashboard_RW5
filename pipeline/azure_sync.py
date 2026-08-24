# -*- coding: utf-8 -*-
"""Azure-backed cache synchronization and cross-machine pipeline locking."""

from __future__ import annotations

import os
import re
import threading
from contextlib import contextmanager
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd
from azure.core.exceptions import HttpResponseError, ResourceExistsError
from azure.storage.blob import BlobServiceClient, ContentSettings

from config import (
    AZURE_CONTAINER_NAME,
    AZURE_STORAGE_CONNECTION_STRING,
    DAILY_DIR,
)


DAILY_BLOB_PREFIX = "daily"
PIPELINE_LOCK_BLOB = "locks/pipeline-update.lock"
LEASE_DURATION_SECONDS = 60
LEASE_RENEW_INTERVAL_SECONDS = 30

_DAILY_BLOB_PATTERN = re.compile(
    r"^daily/(?P<year>\d{4})/(?P<day>\d{4}-\d{2}-\d{2})\.parquet$"
)
_active_lease_guard: "_LeaseGuard | None" = None


@lru_cache(maxsize=1)
def azure_container_client():
    """Return the configured container, creating it when necessary."""
    if not AZURE_STORAGE_CONNECTION_STRING or not AZURE_CONTAINER_NAME:
        raise ValueError(
            "Azure Blob Storage is not configured; set "
            "AZURE_STORAGE_CONNECTION_STRING and AZURE_CONTAINER_NAME"
        )

    service = BlobServiceClient.from_connection_string(
        AZURE_STORAGE_CONNECTION_STRING
    )
    container = service.get_container_client(AZURE_CONTAINER_NAME)
    try:
        container.create_container()
    except ResourceExistsError:
        pass
    return container


def market_daily_blob(day: date) -> str:
    return f"{DAILY_BLOB_PREFIX}/{day.year}/{day.isoformat()}.parquet"


def market_daily_file(day: date) -> Path:
    return DAILY_DIR / str(day.year) / f"{day.isoformat()}.parquet"


def day_from_market_blob(blob_name: str) -> date | None:
    match = _DAILY_BLOB_PATTERN.fullmatch(blob_name)
    if not match or match.group("year") != match.group("day")[:4]:
        return None
    return date.fromisoformat(match.group("day"))


def validate_market_daily_file(file: Path, day: date) -> None:
    """Raise when a market partition is unreadable or belongs to another day."""
    try:
        frame = pd.read_parquet(file, columns=["timestamp_Ams"])
    except Exception as exc:
        raise ValueError(f"Unreadable market daily partition for {day}: {file}") from exc

    if frame.empty:
        raise ValueError(f"Market daily partition is empty for {day}: {file}")

    timestamps = pd.to_datetime(frame["timestamp_Ams"], errors="coerce")
    actual_days = set(timestamps.dropna().dt.date)
    if timestamps.isna().any() or actual_days != {day}:
        raise ValueError(
            f"Market daily partition timestamps do not match {day}: {file}"
        )


def list_market_daily_blobs(*, years: set[int] | None = None) -> dict[date, object]:
    """List canonical daily market partitions currently stored in Azure."""
    result: dict[date, object] = {}
    for blob in azure_container_client().list_blobs(
        name_starts_with=f"{DAILY_BLOB_PREFIX}/"
    ):
        day = day_from_market_blob(blob.name)
        if day is None or (years is not None and day.year not in years):
            continue
        result[day] = blob
    return result


def sync_market_daily_cache(*, years: set[int], logger) -> set[date]:
    """Replace the selected local daily cache with Azure's canonical partitions."""
    remote = list_market_daily_blobs(years=years)
    if not remote:
        logger.info(f"No Azure market daily partitions found for years {sorted(years)}")
        return set()

    container = azure_container_client()
    restored: set[date] = set()

    for day in sorted(remote):
        destination = market_daily_file(day)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.download")
        try:
            content = container.download_blob(market_daily_blob(day)).readall()
            temporary.write_bytes(content)
            validate_market_daily_file(temporary, day)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        restored.add(day)

    logger.info(
        f"Synchronized {len(restored)} market daily partition(s) from Azure "
        f"for years {sorted(years)}"
    )
    return restored


def upload_market_daily_file(
    local_file: Path,
    day: date,
    *,
    overwrite: bool = True,
) -> None:
    """Validate and publish one canonical market daily partition."""
    assert_pipeline_lease_healthy()
    validate_market_daily_file(local_file, day)
    blob = azure_container_client().get_blob_client(market_daily_blob(day))
    with local_file.open("rb") as source:
        blob.upload_blob(
            source,
            overwrite=overwrite,
            content_settings=ContentSettings(content_type="application/octet-stream"),
        )


class _LeaseGuard:
    def __init__(self, lease, *, logger=None):
        self.lease = lease
        self.logger = logger
        self.stop_event = threading.Event()
        self.renewal_error: BaseException | None = None
        self.thread = threading.Thread(
            target=self._renew_loop,
            name="azure-pipeline-lease-renewer",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def _renew_loop(self) -> None:
        while not self.stop_event.wait(LEASE_RENEW_INTERVAL_SECONDS):
            try:
                self.lease.renew()
            except BaseException as exc:  # surfaced to the publishing thread
                self.renewal_error = exc
                if self.logger is not None:
                    self.logger.error(f"Azure pipeline lease renewal failed: {exc}")
                return

    def ensure_healthy(self) -> None:
        if self.renewal_error is not None:
            raise RuntimeError(
                "The Azure pipeline lease was lost; refusing to publish data"
            ) from self.renewal_error

    def close(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5)
        try:
            self.lease.release()
        except HttpResponseError:
            # A lost/expired lease has already stopped protecting the run.
            pass


def assert_pipeline_lease_healthy() -> None:
    """Prevent publishing after the current process has lost its Azure lease."""
    if _active_lease_guard is not None:
        _active_lease_guard.ensure_healthy()


@contextmanager
def azure_pipeline_lease(*, logger=None):
    """Serialize pipeline writers across machines with a renewable blob lease."""
    global _active_lease_guard

    if _active_lease_guard is not None:
        raise RuntimeError("The Azure pipeline lease is already active in this process")

    lock_blob = azure_container_client().get_blob_client(PIPELINE_LOCK_BLOB)
    try:
        lock_blob.upload_blob(b"RW5 pipeline lock", overwrite=False)
    except ResourceExistsError:
        pass

    try:
        lease = lock_blob.acquire_lease(lease_duration=LEASE_DURATION_SECONDS)
    except HttpResponseError as exc:
        if getattr(exc, "status_code", None) == 409:
            raise RuntimeError(
                "Another machine is already running an RW5 pipeline update"
            ) from exc
        raise

    guard = _LeaseGuard(lease, logger=logger)
    _active_lease_guard = guard
    guard.start()
    try:
        yield
        guard.ensure_healthy()
    finally:
        guard.close()
        _active_lease_guard = None
