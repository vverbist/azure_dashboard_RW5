from __future__ import annotations

from io import BytesIO

import pandas as pd
from azure.storage.blob import BlobServiceClient

from .config import get_azure_connection_string, get_azure_container_name


SCADA_FLAG_DTYPES = {
    "scada_available_potential_warning": "boolean",
    "scada_actual_cap_warning": "boolean",
    "scada_setpoint_fallback_applied": "boolean",
    "scada_frozen_signal": "boolean",
}


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
    blob_bytes = container.download_blob(blob_name).readall()
    return pd.read_csv(BytesIO(blob_bytes), dtype=SCADA_FLAG_DTYPES)


def list_dataset_blobs(connection_string: str | None = None, container_name: str | None = None) -> dict[str, list[str]]:
    exports = list_csv_blobs("exports/", connection_string=connection_string, container_name=container_name)
    monthly = list_csv_blobs("monthly/", connection_string=connection_string, container_name=container_name)
    return {"exports": exports, "monthly": monthly, "all": sorted(exports + monthly)}
