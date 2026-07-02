from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional during minimal deployments
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DEFAULT_AZURE_CONTAINER_NAME = "rw5data-turbine-edmij-entsoe"

if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env")


def get_azure_connection_string() -> str | None:
    return os.getenv("AZURE_STORAGE_CONNECTION_STRING")


def get_azure_container_name() -> str:
    return os.getenv("AZURE_CONTAINER_NAME") or DEFAULT_AZURE_CONTAINER_NAME

