# -*- coding: utf-8 -*-
"""
Created on Mon Jun 22 14:32:06 2026

@author: VictorVerbist
"""

from pathlib import Path
import os


from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]

load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
DAILY_DIR = DATA_DIR / "daily"
MONTHLY_DIR = DATA_DIR / "monthly"
EXPORT_DIR = DATA_DIR / "exports"

COUNTRY_CODE = "NL"
ENVIRONMENT = "production"

EDMIJ_USERNAME = os.getenv("EDMIJ_USERNAME")
EDMIJ_PASSWORD = os.getenv("EDMIJ_PASSWORD")

EVIEW_USERNAME = os.getenv("EVIEW_USERNAME")
EVIEW_PASSWORD = os.getenv("EVIEW_PASSWORD")

ENTSOE_TOKEN = os.getenv("ENTSOE_TOKEN")

# InfluxDB v2 (turbine SCADA channels, e.g. AAP / active available power).
# Env keys are IDB_* ("InfluxDB"). Not part of the daily pipeline yet, so
# intentionally kept out of required_vars below;
# fetch_influx_measurements_utc_15min() validates them at call time.
INFLUX_URL = os.getenv("IDB_URL")
INFLUX_TOKEN = os.getenv("IDB_TOKEN")
INFLUX_ORG = os.getenv("IDB_ORG")
INFLUX_BUCKET = os.getenv("IDB_BUCKET")

AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME")

SLEEP_SECONDS = 0.1

# How far back to look for missing daily files when no synced data exists yet at all.
MAX_BACKFILL_LOOKBACK_DAYS = 30

# Trailing window that gets re-checked for NaNs / late-arriving corrections on every
# daily run, even for days whose file already exists.
DAILY_REPAIR_LOOKBACK_DAYS = 14

LOG_DIR = DATA_DIR / "logs"

HTTP_MAX_RETRIES = 3
HTTP_RETRY_BACKOFF_SECONDS = 5

MARKET_REQUIRED_VARS = [
    "ENTSOE_TOKEN",
    "EVIEW_USERNAME",
    "EVIEW_PASSWORD",
    "EDMIJ_USERNAME",
    "EDMIJ_PASSWORD",
    "AZURE_STORAGE_CONNECTION_STRING",
    "AZURE_CONTAINER_NAME",
]


def validate_required_vars(variable_names: list[str]) -> None:
    """Validate credentials at an entry point rather than during module import."""
    missing = [name for name in variable_names if not os.getenv(name)]
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")
