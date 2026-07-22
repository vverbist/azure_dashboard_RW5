# -*- coding: utf-8 -*-
"""
Shared functions for the daily market data pipeline: fetching from EDMIJ/E-View/
ENTSO-E, generating/rebuilding daily-monthly-YTD files, uploading to blob storage,
and NaN detection/repair.

This module does nothing on import — see run_daily_update.py and run_repair.py
for the entry points that actually run it.
"""

import io
import logging
import time
import warnings
from datetime import date, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pandas as pd
import requests
from entsoe import EntsoePandasClient
from influxdb_client import InfluxDBClient
from influxdb_client.client.warnings import MissingPivotFunction

from azure.storage.blob import BlobServiceClient, ContentSettings

from config import (
    DAILY_DIR,
    MONTHLY_DIR,
    EXPORT_DIR,
    LOG_DIR,
    COUNTRY_CODE,
    ENVIRONMENT,
    EDMIJ_USERNAME,
    EDMIJ_PASSWORD,
    EVIEW_USERNAME,
    EVIEW_PASSWORD,
    ENTSOE_TOKEN,
    INFLUX_URL,
    INFLUX_TOKEN,
    INFLUX_ORG,
    INFLUX_BUCKET,
    AZURE_STORAGE_CONNECTION_STRING,
    AZURE_CONTAINER_NAME,
    SLEEP_SECONDS,
    HTTP_MAX_RETRIES,
    HTTP_RETRY_BACKOFF_SECONDS,
)


logger = logging.getLogger("pipeline")


def configure_logging(script_name: str) -> logging.Logger:
    """
    Attach a rotating file handler (LOG_DIR/<script_name>.log) and a console
    handler to the shared "pipeline" logger. Call once from a script's entry point.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        LOG_DIR / f"{script_name}.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def fetch_with_retry(label: str, func, *args, **kwargs):
    """
    Call func(*args, **kwargs), retrying on any exception up to HTTP_MAX_RETRIES
    times with linear backoff. Raises the last exception if all attempts fail.
    """
    last_exc = None

    for attempt in range(1, HTTP_MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                f"{label} failed (attempt {attempt}/{HTTP_MAX_RETRIES}): {exc}"
            )
            if attempt < HTTP_MAX_RETRIES:
                time.sleep(HTTP_RETRY_BACKOFF_SECONDS * attempt)

    logger.error(f"{label} failed after {HTTP_MAX_RETRIES} attempts")
    raise last_exc


# ============================================================
# TIME HELPERS
# ============================================================

def local_period_to_utc(from_date, to_date, tz_local="Europe/Amsterdam"):
    start_local = pd.Timestamp(from_date).tz_localize(tz_local)
    end_local = pd.Timestamp(to_date).tz_localize(tz_local)
    return start_local.tz_convert("UTC"), end_local.tz_convert("UTC")


def utc_15min_timeline(start_utc, end_utc):
    return pd.DataFrame({
        "timestamp_utc": pd.date_range(
            start=start_utc,
            end=end_utc,
            freq="15min",
            inclusive="left",
            tz="UTC",
        )
    })


# ============================================================
# EDMIJ NOMINATIONS
# ============================================================

def fetch_edmij_nominations_utc_15min(from_date, to_date):

    base_url = (
        "https://api.test.edmij.nl"
        if ENVIRONMENT == "staging"
        else "https://api.edmij.nl"
    )

    resource = "https://api.edmij.nl"
    session = requests.Session()

    def login():
        r = session.post(
            f"{base_url}/connect/token",
            data={
                "grant_type": "password",
                "username": EDMIJ_USERNAME,
                "password": EDMIJ_PASSWORD,
                "scope": "openid offline_access roles",
                "resource": resource,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        r.raise_for_status()
        j = r.json()
        return j["access_token"], j["refresh_token"]

    def refresh(refresh_token):
        r = session.post(
            f"{base_url}/connect/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "openid offline_access roles",
                "resource": resource,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        r.raise_for_status()
        j = r.json()
        return j["access_token"], j["refresh_token"]

    def get_day(delivery_date, access_token):
        return session.get(
            f"{base_url}/api/v1/nominations/perAccount",
            params={"deliveryDate": delivery_date},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )

    access_token, refresh_token = login()

    start_day = pd.Timestamp(from_date).date()
    end_day_exclusive = pd.Timestamp(to_date).date()

    rows = []
    d = start_day

    while d < end_day_exclusive:
        delivery_date = d.isoformat()
        logger.info(f"Fetching EDMIJ nominations {delivery_date}")

        r = get_day(delivery_date, access_token)

        if r.status_code == 401:
            access_token, refresh_token = refresh(refresh_token)
            r = get_day(delivery_date, access_token)

        if r.status_code != 200:
            logger.warning(f"EDMIJ error {delivery_date}: {r.status_code} {r.text[:500]}")
            d += timedelta(days=1)
            time.sleep(SLEEP_SECONDS)
            continue

        data = r.json()
        per_account = data.get("perAccount", {})

        for account_id, nominations in per_account.items():
            for n in nominations or []:
                rows.append({
                    "timestamp_utc": n.get("startTime"),
                    "nominated_volume_mwh": n.get("volumeKwh"),
                })

        d += timedelta(days=1)
        time.sleep(SLEEP_SECONDS)

    df = pd.DataFrame(rows)

    if df.empty:
        return pd.DataFrame(columns=["timestamp_utc", "nominated_volume_mwh"])

    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    df["nominated_volume_mwh"] = (
        pd.to_numeric(df["nominated_volume_mwh"], errors="coerce") / 1000 * -1
    )

    return (
        df.dropna(subset=["timestamp_utc"])
        .groupby("timestamp_utc", as_index=False)["nominated_volume_mwh"]
        .sum()
    )


# ============================================================
# E-VIEW DELIVERED VOLUME
# ============================================================

def fetch_eview_delivered_utc_15min(from_date, to_date):
    token_resp = requests.post(
        "https://api.eview.nl/Token",
        data={
            "userName": EVIEW_USERNAME,
            "password": EVIEW_PASSWORD,
            "grant_type": "password",
        },
        timeout=60,
    )
    token_resp.raise_for_status()

    token_json = token_resp.json()
    access_token = f"{token_json['token_type']} {token_json['access_token']}"

    resp = requests.post(
        "https://api.eview.nl/api/export/exportchartdatatoexcel",
        headers={"Authorization": access_token},
        data={
            "DatachannelIds[0]": "108495",
            "DatachannelIds[1]": "108524",
            "DatachannelIds[2]": "108492",
            "DatachannelIds[3]": "108493",
            "showTemperature": "false",
            "From": from_date,
            "Till": to_date,
            "Grouping": "minute",
            "AltUnit": "none",
            "SelectedUsagePerAttribute": "-1",
        },
        timeout=120,
    )
    resp.raise_for_status()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        df = pd.read_excel(
            io.BytesIO(resp.content),
            engine="openpyxl",
            parse_dates=["Tijdstip (van)"],
        )

    df["timestamp_utc"] = (
        df["Tijdstip (van)"]
        .dt.tz_localize(
            "Europe/Amsterdam",
            ambiguous="infer",
            nonexistent="shift_forward",
        )
        .dt.tz_convert("UTC")
    )

    unique_channels = df["Omschrijving"].unique()

    channel_data = {
        ch: df[df["Omschrijving"] == ch].reset_index(drop=True)
        for ch in unique_channels
    }

    def process_channel(dfc, drop_cols, conversion_factor=1 / 1000):
        dfc = dfc.copy()
        dfc.drop(columns=drop_cols, inplace=True, errors="ignore")
        dfc["Verbruik totaal"] = (
            pd.to_numeric(dfc["Verbruik totaal"], errors="coerce")
            * conversion_factor
        )
        return dfc

    usage = process_channel(
        channel_data[unique_channels[2]],
        [
            "Datakanaal",
            "Omschrijving",
            "Tijdstip (tot)",
            "Verbruik laag",
            "Verbruik hoog",
            "Meterstand",
        ],
    )

    production_bpm = process_channel(
        channel_data[unique_channels[0]],
        [
            "Datakanaal",
            "Omschrijving",
            "Tijdstip (tot)",
            "Tijdstip (van)",
            "Verbruik laag",
            "Verbruik hoog",
            "Meterstand",
        ],
    )

    meas = pd.concat(
        [
            usage[["timestamp_utc"]].reset_index(drop=True),
            production_bpm["Verbruik totaal"].reset_index(drop=True),
        ],
        axis=1,
    )

    meas.columns = [
        "timestamp_utc",
        "delivered_volume_mwh",
    ]

    meas = (
        meas
        .set_index("timestamp_utc")
        .resample("15min", label="left", closed="left")
        .sum(min_count=1)
        .reset_index()
    )

    start_utc, end_utc = local_period_to_utc(from_date, to_date)

    meas = meas[
        (meas["timestamp_utc"] >= start_utc)
        & (meas["timestamp_utc"] < end_utc)
    ].copy()

    return meas


# ============================================================
# ENTSO-E PRICES
# ============================================================

def fetch_entsoe_prices_utc_15min(country_code, start_utc, end_utc):
    client = EntsoePandasClient(api_key=ENTSOE_TOKEN)

    da = client.query_day_ahead_prices(
        country_code,
        start=start_utc,
        end=end_utc,
    )

    da = da.to_frame("epex_eur_per_mwh")
    da.index = pd.to_datetime(da.index, utc=True)

    da_15 = (
        da.resample("15min", label="left", closed="left")
        .ffill()
        .reset_index()
        .rename(columns={"index": "timestamp_utc"})
    )

    ib = client.query_imbalance_prices(
        country_code,
        start=start_utc,
        end=end_utc,
        psr_type=None,
    )

    ib.index = pd.to_datetime(ib.index, utc=True)

    if isinstance(ib, pd.Series):
        ib = ib.to_frame("imbalance_price_eur_per_mwh")
    else:
        ib = ib.rename(columns={
            "Long": "imbalance_long_eur_per_mwh",
            "Short": "imbalance_short_eur_per_mwh",
        })

    ib_15 = (
        ib.resample("15min", label="left", closed="left")
        .ffill()
        .reset_index()
        .rename(columns={"index": "timestamp_utc"})
    )

    return da_15, ib_15


# ============================================================
# INFLUXDB TURBINE MEASUREMENTS (AAP / active available power)
# ============================================================
#
# These helpers are NOT wired into the daily pipeline (generate_period /
# run_daily_update) yet - they only exist so AAP and other turbine SCADA channels
# can be retrieved on demand.
#
# AAP ("active available power") is the power a turbine could have produced
# irrespective of curtailment, whereas the E-View `delivered_volume_mwh` is what
# was actually produced. In the InfluxDB SCADA data this is the `PavaVWind`
# measurement (wind-based available power), the same "potential" quantity the
# reference analysis uses as its loss baseline.
#
# Time alignment: InfluxDB stores instantaneous SCADA samples; we aggregate to
# 15-minute means server-side via Flux `aggregateWindow`, with
# `timeSrc: "_start"` so each 15-min value is labelled by the START of its window.
# That matches the rest of the pipeline, which is left-closed / left-labelled
# (see fetch_eview_delivered_utc_15min and utc_15min_timeline), so the timestamps
# line up on merge. As with the other fetchers, `from_date`/`to_date` are plain
# date strings interpreted as Europe/Amsterdam local day boundaries.

# InfluxDB measurement name for active available power.
AAP_MEASUREMENT = "PavaVWind"

# The turbine power channels are 15-min mean power in kW. Converting a mean power
# to energy over one 15-min interval: kW * 0.25 h / 1000 -> MWh. This mirrors the
# reference `compute_losses` (power_cols * dt_hours / 1000).
INTERVAL_HOURS = 0.25
MWH_PER_KWH = 1 / 1000

# (connect timeout ms, read timeout ms) for the Influx client.
INFLUX_TIMEOUT = (10_000, 300_000)


def fetch_influx_measurements_utc_15min(
    from_date,
    to_date,
    measurements: list[str],
    field: str = "value",
) -> pd.DataFrame:
    """
    Query InfluxDB v2 for one or more turbine SCADA measurements and return them
    as a wide 15-minute frame aligned to the pipeline's UTC timeline.

    Each requested measurement becomes one column (named exactly as the
    measurement), holding the 15-minute mean of the given `field`. Values are
    labelled by the start of each window (see module note above) and reindexed
    onto the complete UTC 15-min grid for the period, so gaps show up as NaN.

    Returns a DataFrame with a tz-aware UTC `timestamp_utc` column plus one column
    per requested measurement. Raises ValueError if InfluxDB is not configured or
    no measurements are requested.
    """
    if not measurements:
        raise ValueError("measurements must contain at least one measurement name")

    if not (INFLUX_URL and INFLUX_TOKEN and INFLUX_ORG and INFLUX_BUCKET):
        raise ValueError(
            "InfluxDB is not configured; set INFLUX_URL, INFLUX_TOKEN, "
            "INFLUX_ORG and INFLUX_BUCKET in .env"
        )

    start_utc, end_utc = local_period_to_utc(from_date, to_date)
    timeline = utc_15min_timeline(start_utc, end_utc)

    start_iso = start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    measurement_filter = " or ".join(
        f'r["_measurement"] == "{m}"' for m in measurements
    )

    query = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: time(v: "{start_iso}"), stop: time(v: "{end_iso}"))
  |> filter(fn: (r) => {measurement_filter})
  |> filter(fn: (r) => r["_field"] == "{field}")
  |> aggregateWindow(every: 15m, fn: mean, createEmpty: false, timeSrc: "_start")
  |> keep(columns: ["_time", "_measurement", "_value"])
  |> sort(columns: ["_time"])
'''

    logger.info(
        f"Querying InfluxDB {measurements} from {start_iso} to {end_iso}"
    )

    with InfluxDBClient(
        url=INFLUX_URL,
        token=INFLUX_TOKEN,
        org=INFLUX_ORG,
        timeout=INFLUX_TIMEOUT,
    ) as client:
        # We reshape to wide with pandas pivot_table below, so silence the
        # client's suggestion to add a Flux pivot().
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", MissingPivotFunction)
            df = client.query_api().query_data_frame(query)

    if isinstance(df, list):
        df = pd.concat(df, ignore_index=True) if df else pd.DataFrame()

    if df.empty:
        logger.warning("InfluxDB query returned no data")
        result = timeline.copy()
        for m in measurements:
            result[m] = float("nan")
        return result

    drop_cols = [c for c in ["result", "table", "_start", "_stop"] if c in df.columns]
    df = df.drop(columns=drop_cols, errors="ignore")

    df["_time"] = pd.to_datetime(df["_time"], utc=True, errors="coerce")
    df["_value"] = pd.to_numeric(df["_value"], errors="coerce")

    wide = (
        df.pivot_table(
            index="_time",
            columns="_measurement",
            values="_value",
            aggfunc="last",
        )
        .reindex(columns=measurements)
        .reset_index()
        .rename(columns={"_time": "timestamp_utc"})
    )

    return timeline.merge(wide, on="timestamp_utc", how="left")


def fetch_aap_utc_15min(from_date, to_date) -> pd.DataFrame:
    """
    Fetch the active available power (AAP) turbine channel and return it as energy
    per 15-minute interval, so it is directly comparable to the pipeline's
    `delivered_volume_mwh` (actually produced) column.

    AAP is the InfluxDB `PavaVWind` measurement (a 15-min mean power in kW),
    converted to MWh per interval as kW * 0.25 h / 1000 -> `aap_mwh`.

    Returns a DataFrame with `timestamp_utc` and `aap_mwh`.
    """
    raw = fetch_influx_measurements_utc_15min(from_date, to_date, [AAP_MEASUREMENT])

    result = raw[["timestamp_utc"]].copy()
    result["aap_mwh"] = (
        pd.to_numeric(raw[AAP_MEASUREMENT], errors="coerce")
        * INTERVAL_HOURS
        * MWH_PER_KWH
    )

    return result


# ============================================================
# DATA GENERATION
# ============================================================

def generate_period(from_date: str, to_date: str) -> pd.DataFrame:
    logger.info(f"Generating period {from_date} to {to_date}")

    start_utc, end_utc = local_period_to_utc(from_date, to_date)

    timeline = utc_15min_timeline(start_utc, end_utc)

    nominations_15 = fetch_with_retry(
        "EDMIJ nominations", fetch_edmij_nominations_utc_15min, from_date, to_date
    )
    delivered_15 = fetch_with_retry(
        "E-View delivered volume", fetch_eview_delivered_utc_15min, from_date, to_date
    )
    epex_15, imbalance_15 = fetch_with_retry(
        "ENTSO-E prices", fetch_entsoe_prices_utc_15min, COUNTRY_CODE, start_utc, end_utc
    )

    final = (
        timeline
        .merge(epex_15, on="timestamp_utc", how="left")
        .merge(imbalance_15, on="timestamp_utc", how="left")
        .merge(nominations_15, on="timestamp_utc", how="left")
        .merge(delivered_15, on="timestamp_utc", how="left")
        .sort_values("timestamp_utc")
    )

    final["period_utc"] = (
        final["timestamp_utc"].dt.strftime("%Y-%m-%d %H:%M")
        + " - "
        + (final["timestamp_utc"] + pd.Timedelta(minutes=15)).dt.strftime("%H:%M")
    )

    final["timestamp"] = (
        final["timestamp_utc"]
        .dt.tz_convert("UTC")
        .dt.tz_localize(None)
    )

    final["timestamp_Ams"] = (
        final["timestamp_utc"]
        .dt.tz_convert("Europe/Amsterdam")
        .dt.tz_localize(None)
    )

    cols = [
        "timestamp_Ams",
        "timestamp",
        "period_utc",
        "epex_eur_per_mwh",
        "imbalance_long_eur_per_mwh",
        "imbalance_short_eur_per_mwh",
        "nominated_volume_mwh",
        "delivered_volume_mwh",
    ]

    cols = [c for c in cols if c in final.columns]
    df = final[cols].copy()

    df["volume_long_mwh"] = (
        df["delivered_volume_mwh"] - df["nominated_volume_mwh"]
    ).clip(0, None)

    df["volume_short_mwh"] = (
        df["delivered_volume_mwh"] - df["nominated_volume_mwh"]
    ).clip(None, 0) * -1

    df["volume_imbalance_mwh"] = (
        df["delivered_volume_mwh"] - df["nominated_volume_mwh"]
    )

    df["epex_revenue"] = (
        df["nominated_volume_mwh"] * df["epex_eur_per_mwh"]
    )

    df["imbalance_long_revenue"] = (
        df["volume_long_mwh"] * df["imbalance_long_eur_per_mwh"]
    )

    df["imbalance_short_revenue"] = (
        -df["volume_short_mwh"] * df["imbalance_short_eur_per_mwh"]
    )

    df["imbalance_total_revenue"] = (
        df["imbalance_long_revenue"] + df["imbalance_short_revenue"]
    )

    df["total_revenue"] = (
        df["epex_revenue"]
        + df["imbalance_long_revenue"]
        + df["imbalance_short_revenue"]
    )

    return df


def generate_day(day: date, overwrite: bool = False) -> Path:
    out_dir = DAILY_DIR / str(day.year)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / f"{day.isoformat()}.parquet"

    if out_file.exists() and not overwrite:
        logger.info(f"Skipping existing file: {out_file}")
        return out_file

    from_date = day.isoformat()
    to_date = (day + timedelta(days=1)).isoformat()

    df = generate_period(from_date, to_date)

    df.to_parquet(out_file, index=False)

    logger.info(f"Saved daily file: {out_file}")

    return out_file


def find_last_synced_day() -> date | None:
    """
    Most recent day for which a daily parquet file already exists, or None if
    no daily files exist at all yet.
    """
    files = sorted(DAILY_DIR.glob("*/*.parquet"))

    if not files:
        return None

    return date.fromisoformat(files[-1].stem)


def rebuild_ytd(year: int) -> Path:
    files = sorted((DAILY_DIR / str(year)).glob("*.parquet"))

    if not files:
        raise FileNotFoundError(f"No daily files found for {year}")

    ytd = pd.concat(
        [pd.read_parquet(file) for file in files],
        ignore_index=True,
    )

    ytd = ytd.sort_values("timestamp_Ams")

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    out_file = EXPORT_DIR / f"{year}_ytd.csv"

    ytd.to_csv(out_file, index=False)

    logger.info(f"Saved YTD file: {out_file}")

    return out_file


def rebuild_month(year: int, month: int) -> Path:
    month_dir = MONTHLY_DIR / str(year)
    month_dir.mkdir(parents=True, exist_ok=True)

    daily_files = sorted((DAILY_DIR / str(year)).glob(f"{year}-{month:02d}-*.parquet"))

    if not daily_files:
        raise FileNotFoundError(f"No daily files found for {year}-{month:02d}")

    monthly = pd.concat(
        [pd.read_parquet(file) for file in daily_files],
        ignore_index=True,
    )

    monthly = monthly.sort_values("timestamp_Ams")

    out_file = month_dir / f"{year}-{month:02d}.csv"
    monthly.to_csv(out_file, index=False)

    logger.info(f"Saved monthly file: {out_file}")

    return out_file


def backfill_days(start_day: date, end_day: date, overwrite: bool = False) -> list[date]:
    """
    Generate daily parquet files from start_day through end_day, inclusive.

    Does not rebuild monthly/YTD exports - callers decide which months/years to
    rebuild since they may also be touched by a separate repair pass.

    Returns the list of days that failed to generate.
    """
    failed_days = []
    d = start_day

    while d <= end_day:
        try:
            generate_day(d, overwrite=overwrite)
        except Exception as e:
            logger.error(f"Failed for {d}: {e}")
            failed_days.append(d)

        d += timedelta(days=1)

    return failed_days


def upload_file_to_blob(local_file: Path, blob_name: str):
    blob_service_client = BlobServiceClient.from_connection_string(
        AZURE_STORAGE_CONNECTION_STRING
    )

    container_client = blob_service_client.get_container_client(
        AZURE_CONTAINER_NAME
    )

    try:
        container_client.create_container()
    except Exception:
        pass

    content_type = "text/csv" if local_file.suffix == ".csv" else "application/octet-stream"

    blob_client = container_client.get_blob_client(blob_name)

    with open(local_file, "rb") as f:
        blob_client.upload_blob(
            f,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

    logger.info(f"Uploaded to Azure Blob: {blob_name}")


# ============================================================
# DATA QUALITY / NAN INSPECTION AND REPAIR
# ============================================================

REPAIR_SOURCE_COLUMNS = [
    "epex_eur_per_mwh",
    "imbalance_long_eur_per_mwh",
    "imbalance_short_eur_per_mwh",
    "nominated_volume_mwh",
    "delivered_volume_mwh",
]


PRICE_COLUMNS = {
    "epex_eur_per_mwh",
    "imbalance_long_eur_per_mwh",
    "imbalance_short_eur_per_mwh",
}


def daily_file_for_day(day: date) -> Path:
    return DAILY_DIR / str(day.year) / f"{day.isoformat()}.parquet"


def recalculate_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Recalculate derived columns after source columns have been patched.
    """
    df = df.copy()

    df["volume_long_mwh"] = (
        df["delivered_volume_mwh"] - df["nominated_volume_mwh"]
    ).clip(0, None)

    df["volume_short_mwh"] = (
        df["delivered_volume_mwh"] - df["nominated_volume_mwh"]
    ).clip(None, 0) * -1

    df["volume_imbalance_mwh"] = (
        df["delivered_volume_mwh"] - df["nominated_volume_mwh"]
    )

    df["epex_revenue"] = (
        df["nominated_volume_mwh"] * df["epex_eur_per_mwh"]
    )

    df["imbalance_long_revenue"] = (
        df["volume_long_mwh"] * df["imbalance_long_eur_per_mwh"]
    )

    df["imbalance_short_revenue"] = (
        -df["volume_short_mwh"] * df["imbalance_short_eur_per_mwh"]
    )

    df["imbalance_total_revenue"] = (
        df["imbalance_long_revenue"] + df["imbalance_short_revenue"]
    )

    df["total_revenue"] = (
        df["epex_revenue"]
        + df["imbalance_long_revenue"]
        + df["imbalance_short_revenue"]
    )

    return df


def find_nan_timestamps_in_day(
    day: date,
    source_columns: list[str] | None = None,
) -> pd.DataFrame:
    """
    Return exact timestamps where one or more source columns are NaN
    for a single daily parquet file.

    This function does not modify anything.
    """
    source_columns = source_columns or REPAIR_SOURCE_COLUMNS
    file = daily_file_for_day(day)

    if not file.exists():
        logger.info(f"No daily file found for {day}: {file}")
        return pd.DataFrame()

    df = pd.read_parquet(file)

    cols_to_check = [col for col in source_columns if col in df.columns]

    if not cols_to_check:
        logger.info(f"No source columns found in {file}")
        return pd.DataFrame()

    nan_mask = df[cols_to_check].isna()
    rows_with_nan = nan_mask.any(axis=1)

    if not rows_with_nan.any():
        logger.info(f"No NaN values found for {day}")
        return pd.DataFrame()

    result = df.loc[rows_with_nan, ["timestamp_Ams", "timestamp"]].copy()

    result["missing_columns"] = nan_mask.loc[rows_with_nan].apply(
        lambda row: [col for col, is_missing in row.items() if is_missing],
        axis=1,
    )

    result["missing_count"] = result["missing_columns"].apply(len)

    return result


def report_nan_timestamps_for_period(
    start_day: date,
    end_day: date,
    source_columns: list[str] | None = None,
    export_csv: bool = False,
) -> pd.DataFrame:
    """
    Inspect a date range and report where NaN values exist.

    This function does not modify anything.

    Example:
        report_nan_timestamps_for_period(
            date(2026, 1, 1),
            date(2026, 2, 1),
            export_csv=True,
        )
    """
    source_columns = source_columns or REPAIR_SOURCE_COLUMNS

    reports = []

    d = start_day

    while d <= end_day:
        day_report = find_nan_timestamps_in_day(
            d,
            source_columns=source_columns,
        )

        if not day_report.empty:
            day_report.insert(0, "day", d)
            reports.append(day_report)

        d += timedelta(days=1)

    if not reports:
        logger.info(f"No NaN values found from {start_day} to {end_day}")
        return pd.DataFrame()

    report = pd.concat(reports, ignore_index=True)

    logger.info(f"Found {len(report)} timestamps with NaN values")
    logger.info("\n" + report.to_string(index=False))

    if export_csv:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)

        out_file = EXPORT_DIR / f"nan_report_{start_day}_{end_day}.csv"

        report_for_export = report.copy()
        report_for_export["missing_columns"] = report_for_export[
            "missing_columns"
        ].apply(lambda cols: ", ".join(cols))

        report_for_export.to_csv(out_file, index=False)

        logger.info(f"Saved NaN report: {out_file}")

    return report


def fetch_missing_source_for_day(
    day: date,
    missing_columns: set[str],
) -> pd.DataFrame:
    """
    Fetch only the source data needed for the missing columns.

    - delivered_volume_mwh      -> E-View only
    - nominated_volume_mwh      -> EDMIJ only
    - price / imbalance columns -> ENTSO-E only
    """
    from_date = day.isoformat()
    to_date = (day + timedelta(days=1)).isoformat()

    frames = []

    if "delivered_volume_mwh" in missing_columns:
        logger.info(f"Fetching E-View delivered volume for {day}")
        delivered_15 = fetch_with_retry(
            "E-View delivered volume", fetch_eview_delivered_utc_15min, from_date, to_date
        )
        frames.append(delivered_15)

    if "nominated_volume_mwh" in missing_columns:
        logger.info(f"Fetching EDMIJ nominations for {day}")
        nominations_15 = fetch_with_retry(
            "EDMIJ nominations", fetch_edmij_nominations_utc_15min, from_date, to_date
        )
        frames.append(nominations_15)

    if missing_columns.intersection(PRICE_COLUMNS):
        logger.info(f"Fetching ENTSO-E prices for {day}")

        start_utc, end_utc = local_period_to_utc(from_date, to_date)

        epex_15, imbalance_15 = fetch_with_retry(
            "ENTSO-E prices", fetch_entsoe_prices_utc_15min, COUNTRY_CODE, start_utc, end_utc
        )

        frames.extend([epex_15, imbalance_15])

    if not frames:
        return pd.DataFrame(columns=["timestamp_utc", "timestamp"])

    refreshed = frames[0].copy()

    for frame in frames[1:]:
        refreshed = refreshed.merge(
            frame,
            on="timestamp_utc",
            how="outer",
        )

    refreshed["timestamp_utc"] = pd.to_datetime(
        refreshed["timestamp_utc"],
        utc=True,
        errors="coerce",
    )

    refreshed = refreshed.dropna(subset=["timestamp_utc"])

    refreshed["timestamp"] = (
        refreshed["timestamp_utc"]
        .dt.tz_convert("UTC")
        .dt.tz_localize(None)
    )

    return refreshed


def repair_nan_timestamps_for_day(
    day: date,
    source_columns: list[str] | None = None,
    rebuild_exports: bool = True,
    upload_exports: bool = True,
) -> bool:
    """
    Manually repair only the specific timestamps and source columns that are NaN
    for one daily parquet file.

    This function:
    - reads the existing daily parquet file
    - finds exact NaN timestamps
    - fetches only the source data needed for the missing columns
    - patches only cells that are currently NaN
    - recalculates derived columns
    - optionally rebuilds and uploads the affected month and YTD export

    Returns True if the daily file was changed.
    """
    source_columns = source_columns or REPAIR_SOURCE_COLUMNS
    file = daily_file_for_day(day)

    if not file.exists():
        logger.info(f"No existing daily file to repair for {day}: {file}")
        return False

    missing_periods = find_nan_timestamps_in_day(
        day,
        source_columns=source_columns,
    )

    if missing_periods.empty:
        logger.info(f"No NaN timestamps found for {day}")
        return False

    logger.info(f"Found {len(missing_periods)} timestamps with NaNs for {day}")

    missing_columns_for_day = set()

    for cols in missing_periods["missing_columns"]:
        missing_columns_for_day.update(cols)

    logger.info(f"Missing source columns for {day}: {sorted(missing_columns_for_day)}")

    existing = pd.read_parquet(file)

    refreshed = fetch_missing_source_for_day(
        day,
        missing_columns_for_day,
    )

    if refreshed.empty:
        logger.info(f"No refreshed source data returned for {day}")
        return False

    existing = existing.copy()
    refreshed = refreshed.copy()

    existing["timestamp"] = pd.to_datetime(
        existing["timestamp"],
        errors="coerce",
    )

    refreshed["timestamp"] = pd.to_datetime(
        refreshed["timestamp"],
        errors="coerce",
    )

    existing = existing.dropna(subset=["timestamp"])
    refreshed = refreshed.dropna(subset=["timestamp"])

    existing = existing.set_index("timestamp")
    refreshed = refreshed.set_index("timestamp")

    changed = False
    patched_cells = 0

    for _, row in missing_periods.iterrows():
        ts = pd.to_datetime(row["timestamp"])
        missing_columns = row["missing_columns"]

        if ts not in refreshed.index:
            logger.info(f"No refreshed row found for timestamp {ts}")
            continue

        for col in missing_columns:
            if col not in refreshed.columns:
                logger.info(f"Column {col} not found in refreshed data")
                continue

            old_value = existing.at[ts, col]
            new_value = refreshed.at[ts, col]

            if pd.isna(old_value) and not pd.isna(new_value):
                existing.at[ts, col] = new_value
                changed = True
                patched_cells += 1
                logger.info(f"Patched {ts} | {col}: NaN -> {new_value}")

    if not changed:
        logger.info(f"No NaN values could be repaired for {day}")
        return False

    existing = existing.reset_index()

    existing = recalculate_derived_columns(existing)
    existing = existing.sort_values("timestamp_Ams")

    existing.to_parquet(file, index=False)

    logger.info(f"Saved repaired daily file: {file}")
    logger.info(f"Patched cells: {patched_cells}")

    remaining = find_nan_timestamps_in_day(
        day,
        source_columns=source_columns,
    )

    if remaining.empty:
        logger.info(f"All checked NaNs repaired for {day}")
    else:
        logger.info(f"Remaining NaN timestamps for {day}:\n{remaining.to_string(index=False)}")

    if rebuild_exports:
        monthly_file = rebuild_month(day.year, day.month)
        ytd_file = rebuild_ytd(day.year)

        if upload_exports:
            upload_file_to_blob(
                monthly_file,
                f"monthly/{day.year}/{monthly_file.name}",
            )

            upload_file_to_blob(
                ytd_file,
                f"exports/{day.year}_ytd.csv",
            )

    return True


def repair_nan_timestamps_for_period(
    start_day: date,
    end_day: date,
    source_columns: list[str] | None = None,
    rebuild_exports: bool = True,
    upload_exports: bool = True,
) -> tuple[set[date], list[date]]:
    """
    Manually repair NaN timestamps for a period.

    Example:
        repair_nan_timestamps_for_period(
            date(2026, 1, 1),
            date(2026, 2, 1),
        )

    Returns (changed_days, failed_days).
    """
    changed_days = set()
    failed_days = []

    d = start_day

    while d <= end_day:
        try:
            changed = repair_nan_timestamps_for_day(
                d,
                source_columns=source_columns,
                rebuild_exports=False,
                upload_exports=False,
            )

            if changed:
                changed_days.add(d)

        except Exception as e:
            logger.error(f"Failed to repair {d}: {e}")
            failed_days.append(d)

        d += timedelta(days=1)

    if rebuild_exports and changed_days:
        touched_months = {(d.year, d.month) for d in changed_days}
        touched_years = {d.year for d in changed_days}

        for year, month in sorted(touched_months):
            monthly_file = rebuild_month(year, month)

            if upload_exports:
                upload_file_to_blob(
                    monthly_file,
                    f"monthly/{year}/{monthly_file.name}",
                )

        for year in sorted(touched_years):
            ytd_file = rebuild_ytd(year)

            if upload_exports:
                upload_file_to_blob(
                    ytd_file,
                    f"exports/{year}_ytd.csv",
                )

    logger.info(f"Changed days: {sorted(changed_days)}")

    if failed_days:
        logger.error(f"Failed days: {sorted(failed_days)}")

    return changed_days, failed_days
