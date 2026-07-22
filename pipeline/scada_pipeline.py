# -*- coding: utf-8 -*-
"""Manual SCADA retrieval, storage, processing, and market-data enrichment."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient
from influxdb_client import InfluxDBClient

from config import (
    AZURE_CONTAINER_NAME,
    AZURE_STORAGE_CONNECTION_STRING,
    DAILY_DIR,
    DATA_DIR,
    INFLUX_BUCKET,
    INFLUX_ORG,
    INFLUX_TOKEN,
    INFLUX_URL,
)
from pipeline_lib import (
    INFLUX_TIMEOUT,
    INTERVAL_HOURS,
    MWH_PER_KWH,
    fetch_influx_measurements_utc_15min,
    fetch_with_retry,
    local_period_to_utc,
    rebuild_month,
    rebuild_ytd,
    upload_file_to_blob,
    utc_15min_timeline,
)


RAW_SIGNAL_COLUMNS = ["P", "PavaVWind", "AbstMaxP", "PSet1", "Vwind"]

POWER_COLUMN_MAP = {
    "P": "scada_actual_power_kw",
    "PavaVWind": "scada_wind_potential_power_kw",
    "AbstMaxP": "scada_technically_available_power_kw",
    "PSet1": "scada_ems_setpoint_kw",
    "Vwind": "scada_wind_speed_mps",
}

PROCESSED_DATA_COLUMNS = [
    "scada_actual_power_kw",
    "scada_wind_potential_power_kw",
    "scada_technically_available_power_kw",
    "scada_ems_setpoint_kw",
    "scada_effective_power_cap_kw",
    "scada_wind_speed_mps",
    "scada_actual_energy_mwh",
    "scada_wind_potential_energy_mwh",
    "scada_technically_available_energy_mwh",
    "scada_effective_cap_energy_mwh",
    "scada_technical_loss_mwh",
    "scada_dispatch_loss_mwh",
    "scada_underperformance_loss_mwh",
    "scada_total_loss_mwh",
    "scada_loss_balance_error_mwh",
    "scada_available_above_potential_kw",
    "scada_actual_above_cap_kw",
    "scada_available_potential_warning",
    "scada_actual_cap_warning",
    "scada_setpoint_fallback_applied",
    "scada_frozen_signal",
]

# Columns emitted by pre-release local trials that must not survive a rebuild.
LEGACY_SCADA_COLUMNS = ["scada_hierarchy_violation"]

SCADA_DIR = DATA_DIR / "scada"
RAW_SCADA_DIR = SCADA_DIR / "raw"
PROCESSED_SCADA_DIR = SCADA_DIR / "processed"
LOCK_FILE = DATA_DIR / ".pipeline_update.lock"

AVAILABLE_POTENTIAL_WARNING_KW = 1.0
ACTUAL_CAP_WARNING_KW = 50.0
ACTUAL_CAP_PERSISTENCE_MIN_KW = 1.0
ACTUAL_CAP_PERSISTENCE_INTERVALS = 2
LOSS_BALANCE_WARNING_MWH = 0.05
LOSS_BALANCE_WARNING_FRACTION = 0.05
FROZEN_POWER_TOLERANCE_KW = 0.001
FROZEN_WIND_TOLERANCE_MPS = 0.001
FROZEN_MIN_INTERVALS = 4

ENERGY_AND_LOSS_COLUMNS = [
    "scada_actual_energy_mwh",
    "scada_wind_potential_energy_mwh",
    "scada_technically_available_energy_mwh",
    "scada_effective_cap_energy_mwh",
    "scada_technical_loss_mwh",
    "scada_dispatch_loss_mwh",
    "scada_underperformance_loss_mwh",
    "scada_total_loss_mwh",
    "scada_loss_balance_error_mwh",
]


def days_inclusive(start_day: date, end_day: date) -> list[date]:
    if start_day > end_day:
        return []
    return [
        start_day + timedelta(days=offset)
        for offset in range((end_day - start_day).days + 1)
    ]


def contiguous_day_ranges(days: list[date]) -> list[tuple[date, date]]:
    """Return inclusive contiguous ranges for a collection of dates."""
    ordered = sorted(set(days))
    if not ordered:
        return []

    ranges: list[tuple[date, date]] = []
    range_start = ordered[0]
    previous = ordered[0]

    for current in ordered[1:]:
        if current != previous + timedelta(days=1):
            ranges.append((range_start, previous))
            range_start = current
        previous = current

    ranges.append((range_start, previous))
    return ranges


def raw_scada_file(day: date) -> Path:
    return RAW_SCADA_DIR / str(day.year) / f"{day.isoformat()}.parquet"


def processed_scada_file(day: date) -> Path:
    return PROCESSED_SCADA_DIR / str(day.year) / f"{day.isoformat()}.parquet"


def raw_scada_blob(day: date) -> str:
    return f"scada/raw/{day.year}/{day.isoformat()}.parquet"


def processed_scada_blob(day: date) -> str:
    return f"scada/processed/{day.year}/{day.isoformat()}.parquet"


def market_daily_file(day: date) -> Path:
    return DAILY_DIR / str(day.year) / f"{day.isoformat()}.parquet"


def expected_timestamps_for_day(day: date) -> pd.Series:
    start_utc, end_utc = local_period_to_utc(
        day.isoformat(),
        (day + timedelta(days=1)).isoformat(),
    )
    return utc_15min_timeline(start_utc, end_utc)["timestamp_utc"]


def normalize_raw_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Select the direct query output without deriving or renaming signals."""
    required = ["timestamp_utc", *RAW_SIGNAL_COLUMNS]
    missing = [column for column in required if column not in raw.columns]
    if missing:
        raise ValueError(f"Raw SCADA result is missing columns: {missing}")

    result = raw[required].copy()
    result["timestamp_utc"] = pd.to_datetime(
        result["timestamp_utc"], utc=True, errors="coerce"
    )
    result = result.dropna(subset=["timestamp_utc"])

    for column in RAW_SIGNAL_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    return (
        result.sort_values("timestamp_utc")
        .drop_duplicates(subset="timestamp_utc", keep="last")
        .reset_index(drop=True)
    )


def extract_raw_day(raw_period: pd.DataFrame, day: date) -> pd.DataFrame:
    raw = normalize_raw_frame(raw_period)
    local_dates = raw["timestamp_utc"].dt.tz_convert("Europe/Amsterdam").dt.date
    return raw.loc[local_dates == day].reset_index(drop=True)


def validate_raw_day(raw: pd.DataFrame, day: date) -> list[str]:
    """Return validation problems; signal-level NaNs are reported separately."""
    problems: list[str] = []
    required = ["timestamp_utc", *RAW_SIGNAL_COLUMNS]

    missing_columns = [column for column in required if column not in raw.columns]
    if missing_columns:
        return [f"missing columns: {missing_columns}"]

    timestamps = pd.to_datetime(raw["timestamp_utc"], utc=True, errors="coerce")
    expected = expected_timestamps_for_day(day)

    if timestamps.isna().any():
        problems.append("invalid timestamps")
    if timestamps.duplicated().any():
        problems.append("duplicate timestamps")
    if len(timestamps) != len(expected):
        problems.append(f"expected {len(expected)} rows, found {len(timestamps)}")
    elif set(timestamps) != set(expected):
        problems.append("timestamps do not match the expected local-day window")

    if raw[RAW_SIGNAL_COLUMNS].isna().all(axis=None):
        problems.append("all SCADA signal values are missing")

    return problems


def raw_day_is_usable(file: Path, day: date) -> bool:
    if not file.exists():
        return False
    try:
        return not validate_raw_day(pd.read_parquet(file), day)
    except Exception:
        return False


def atomic_write_parquet(frame: pd.DataFrame, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def partition_raw_cache(
    source: Path,
    start_day: date,
    end_day: date,
    *,
    overwrite: bool = False,
) -> list[date]:
    """Import an existing multi-day raw cache into validated daily partitions."""
    if source.suffix.lower() == ".parquet":
        cached = pd.read_parquet(source)
    elif source.suffix.lower() == ".csv":
        cached = pd.read_csv(source, low_memory=False)
    else:
        raise ValueError(f"Unsupported SCADA cache format: {source.suffix}")

    cached = normalize_raw_frame(cached)
    selected_days = days_inclusive(start_day, end_day)
    partitions: dict[date, pd.DataFrame] = {}

    # Validate the entire requested period before writing any partition. This
    # prevents a partial migration when the source cache contains a gap.
    for day in selected_days:
        raw_day = extract_raw_day(cached, day)
        problems = validate_raw_day(raw_day, day)
        if problems:
            raise ValueError(
                f"Cached raw SCADA validation failed for {day}: {', '.join(problems)}"
            )
        partitions[day] = raw_day

    imported_days: list[date] = []
    for day, raw_day in partitions.items():
        destination = raw_scada_file(day)
        if not overwrite and raw_day_is_usable(destination, day):
            continue
        atomic_write_parquet(raw_day, destination)
        imported_days.append(day)

    return imported_days


def azure_container_client():
    if not AZURE_STORAGE_CONNECTION_STRING or not AZURE_CONTAINER_NAME:
        raise ValueError(
            "Azure Blob Storage is not configured; set "
            "AZURE_STORAGE_CONNECTION_STRING and AZURE_CONTAINER_NAME"
        )
    service = BlobServiceClient.from_connection_string(
        AZURE_STORAGE_CONNECTION_STRING
    )
    return service.get_container_client(AZURE_CONTAINER_NAME)


def restore_raw_from_azure(day: date, logger) -> bool:
    """Restore a raw daily partition locally when Azure already has it."""
    destination = raw_scada_file(day)
    try:
        content = (
            azure_container_client()
            .download_blob(raw_scada_blob(day))
            .readall()
        )
    except ResourceNotFoundError:
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.download")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()

    if not raw_day_is_usable(destination, day):
        logger.warning(f"Azure raw SCADA partition failed validation: {raw_scada_blob(day)}")
        return False

    logger.info(f"Restored raw SCADA from Azure: {raw_scada_blob(day)}")
    return True


def check_influx_connection() -> None:
    """Fail quickly with a useful error when eCatcher/InfluxDB is unavailable."""
    if not (INFLUX_URL and INFLUX_TOKEN and INFLUX_ORG and INFLUX_BUCKET):
        raise ValueError(
            "InfluxDB is not configured; set IDB_URL, IDB_TOKEN, IDB_ORG "
            "and IDB_BUCKET"
        )

    try:
        with InfluxDBClient(
            url=INFLUX_URL,
            token=INFLUX_TOKEN,
            org=INFLUX_ORG,
            timeout=INFLUX_TIMEOUT,
        ) as client:
            health = client.health()
    except Exception as exc:
        raise ConnectionError(
            "InfluxDB is unreachable. Connect the turbine in eCatcher and run "
            "the command again. No new SCADA query was started."
        ) from exc

    status = str(getattr(health, "status", "")).lower()
    if status and status != "pass":
        raise ConnectionError(f"InfluxDB health check returned status '{status}'")


def detect_frozen_signal_runs(processed: pd.DataFrame) -> pd.Series:
    """Mark runs of effectively unchanged physical signals lasting >= 1 hour."""
    compared_columns = [
        "scada_actual_power_kw",
        "scada_wind_potential_power_kw",
        "scada_technically_available_power_kw",
        "scada_wind_speed_mps",
    ]
    tolerances = pd.Series(
        {
            "scada_actual_power_kw": FROZEN_POWER_TOLERANCE_KW,
            "scada_wind_potential_power_kw": FROZEN_POWER_TOLERANCE_KW,
            "scada_technically_available_power_kw": FROZEN_POWER_TOLERANCE_KW,
            "scada_wind_speed_mps": FROZEN_WIND_TOLERANCE_MPS,
        }
    )

    values = processed[compared_columns]
    complete = values.notna().all(axis=1)
    same_as_previous = values.diff().abs().le(tolerances).all(axis=1)
    same_as_previous &= complete & complete.shift(1, fill_value=False)

    run_id = (~same_as_previous).cumsum()
    run_length = run_id.groupby(run_id).transform("size")
    return complete & (run_length >= FROZEN_MIN_INTERVALS)


def process_raw_scada(raw: pd.DataFrame) -> pd.DataFrame:
    """Create descriptive power, energy, and loss fields from raw ENERCON data."""
    source = normalize_raw_frame(raw)
    processed = source.rename(columns=POWER_COLUMN_MAP)

    actual = processed["scada_actual_power_kw"]
    potential = processed["scada_wind_potential_power_kw"]
    available = processed["scada_technically_available_power_kw"]
    setpoint = processed["scada_ems_setpoint_kw"]

    fallback = setpoint.isna() & available.notna()
    effective_setpoint = setpoint.where(setpoint.notna(), available)
    effective_cap = pd.concat([available, effective_setpoint], axis=1).min(
        axis=1, skipna=False
    )

    processed["scada_effective_power_cap_kw"] = effective_cap
    processed["scada_setpoint_fallback_applied"] = fallback

    energy_factor = INTERVAL_HOURS * MWH_PER_KWH
    processed["scada_actual_energy_mwh"] = actual * energy_factor
    processed["scada_wind_potential_energy_mwh"] = potential * energy_factor
    processed["scada_technically_available_energy_mwh"] = available * energy_factor
    processed["scada_effective_cap_energy_mwh"] = effective_cap * energy_factor

    technical_loss_kw = (potential - available).clip(lower=0)
    dispatch_loss_kw = (available - effective_cap).clip(lower=0)
    underperformance_loss_kw = (effective_cap - actual).clip(lower=0)
    total_loss_kw = (potential - actual).clip(lower=0)

    processed["scada_technical_loss_mwh"] = technical_loss_kw * energy_factor
    processed["scada_dispatch_loss_mwh"] = dispatch_loss_kw * energy_factor
    processed["scada_underperformance_loss_mwh"] = (
        underperformance_loss_kw * energy_factor
    )
    processed["scada_total_loss_mwh"] = total_loss_kw * energy_factor
    processed["scada_loss_balance_error_mwh"] = (
        processed["scada_total_loss_mwh"]
        - processed[
            [
                "scada_technical_loss_mwh",
                "scada_dispatch_loss_mwh",
                "scada_underperformance_loss_mwh",
            ]
        ].sum(axis=1, min_count=3)
    )

    available_above_potential = (available - potential).clip(lower=0)
    actual_above_cap = (actual - effective_cap).clip(lower=0)
    processed["scada_available_above_potential_kw"] = available_above_potential
    processed["scada_actual_above_cap_kw"] = actual_above_cap
    processed["scada_available_potential_warning"] = (
        available_above_potential > AVAILABLE_POTENTIAL_WARNING_KW
    )

    above_persistence_floor = (
        actual_above_cap > ACTUAL_CAP_PERSISTENCE_MIN_KW
    )
    part_of_persistent_run = above_persistence_floor & (
        above_persistence_floor.shift(1, fill_value=False)
        | above_persistence_floor.shift(-1, fill_value=False)
    )
    processed["scada_actual_cap_warning"] = (
        (actual_above_cap > ACTUAL_CAP_WARNING_KW)
        | part_of_persistent_run
    )

    frozen_signal = detect_frozen_signal_runs(processed)
    processed["scada_frozen_signal"] = frozen_signal

    # Preserve the descriptive power/wind values so the frozen source values
    # remain inspectable, but exclude invalid derived analysis from KPIs.
    processed.loc[frozen_signal, ENERGY_AND_LOSS_COLUMNS] = float("nan")
    processed.loc[
        frozen_signal,
        ["scada_available_above_potential_kw", "scada_actual_above_cap_kw"],
    ] = float("nan")
    processed.loc[
        frozen_signal,
        ["scada_available_potential_warning", "scada_actual_cap_warning"],
    ] = False

    processed.insert(
        1,
        "timestamp_Ams",
        processed["timestamp_utc"]
        .dt.tz_convert("Europe/Amsterdam")
        .dt.tz_localize(None),
    )

    output_columns = ["timestamp_utc", "timestamp_Ams", *PROCESSED_DATA_COLUMNS]
    return processed[output_columns].copy()


def enrich_market_day(day: date, processed: pd.DataFrame) -> Path | None:
    """Replace the SCADA portion of one existing combined daily dataset."""
    destination = market_daily_file(day)
    if not destination.exists():
        return None

    market = pd.read_parquet(destination)
    market["timestamp"] = pd.to_datetime(market["timestamp"], errors="coerce")

    enrichment = processed[["timestamp_utc", *PROCESSED_DATA_COLUMNS]].copy()
    enrichment["timestamp"] = (
        pd.to_datetime(enrichment["timestamp_utc"], utc=True, errors="coerce")
        .dt.tz_convert("UTC")
        .dt.tz_localize(None)
    )
    enrichment = enrichment.drop(columns="timestamp_utc")

    market = market.drop(
        columns=[*PROCESSED_DATA_COLUMNS, *LEGACY_SCADA_COLUMNS], errors="ignore"
    )
    combined = (
        market.merge(enrichment, on="timestamp", how="left", validate="one_to_one")
        .sort_values("timestamp_Ams")
        .reset_index(drop=True)
    )
    atomic_write_parquet(combined, destination)
    return destination


def scada_quality_summary(processed: pd.DataFrame) -> dict[str, object]:
    daily_balance_error = processed["scada_loss_balance_error_mwh"].sum(
        min_count=1
    )
    total_loss = processed["scada_total_loss_mwh"].sum(min_count=1)
    if pd.isna(total_loss):
        balance_warning_threshold = float("nan")
    else:
        balance_warning_threshold = max(
            LOSS_BALANCE_WARNING_MWH,
            abs(float(total_loss)) * LOSS_BALANCE_WARNING_FRACTION,
        )
    balance_warning = (
        False
        if pd.isna(daily_balance_error) or pd.isna(balance_warning_threshold)
        else abs(float(daily_balance_error)) > balance_warning_threshold
    )
    return {
        "rows": len(processed),
        "missing_values": processed[PROCESSED_DATA_COLUMNS].isna().sum().to_dict(),
        "setpoint_fallbacks": int(
            processed["scada_setpoint_fallback_applied"].sum()
        ),
        "frozen_intervals": int(processed["scada_frozen_signal"].sum()),
        "available_potential_warnings": int(
            processed["scada_available_potential_warning"].sum()
        ),
        "actual_cap_warnings": int(processed["scada_actual_cap_warning"].sum()),
        "maximum_available_above_potential_kw": float(
            processed["scada_available_above_potential_kw"].max(skipna=True)
        ),
        "maximum_actual_above_cap_kw": float(
            processed["scada_actual_above_cap_kw"].max(skipna=True)
        ),
        "maximum_interval_loss_balance_error_mwh": float(
            processed["scada_loss_balance_error_mwh"].abs().max(skipna=True)
        ),
        "daily_loss_balance_error_mwh": float(daily_balance_error),
        "loss_balance_warning_threshold_mwh": balance_warning_threshold,
        "loss_balance_warning": balance_warning,
    }


@contextmanager
def pipeline_update_lock():
    """Prevent the manual SCADA and scheduled market writers from overlapping."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(
            f"Another pipeline update appears to be running ({LOCK_FILE})."
        ) from exc

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as lock:
            lock.write(str(os.getpid()))
        yield
    finally:
        LOCK_FILE.unlink(missing_ok=True)


def update_scada_period(
    start_day: date,
    end_day: date,
    *,
    logger,
    refresh: bool = False,
    dry_run: bool = False,
    upload: bool = True,
) -> set[date]:
    """Retrieve, persist, process, and merge SCADA for an inclusive date range."""
    days = days_inclusive(start_day, end_day)
    if not days:
        logger.info("No SCADA dates selected")
        return set()

    logger.info(f"SCADA update window: {start_day} through {end_day}")

    if dry_run:
        for day in days:
            raw_state = "cached locally" if raw_day_is_usable(raw_scada_file(day), day) else "not cached locally"
            market_state = "market file exists" if market_daily_file(day).exists() else "market file missing"
            logger.info(f"Dry run {day}: {raw_state}; {market_state}")
        logger.info("Dry run completed; no network queries or file changes were made")
        return set()

    with pipeline_update_lock():
        if not refresh and upload:
            for day in days:
                local_file = raw_scada_file(day)
                if raw_day_is_usable(local_file, day):
                    continue
                restore_raw_from_azure(day, logger)

        query_days = (
            days
            if refresh
            else [day for day in days if not raw_day_is_usable(raw_scada_file(day), day)]
        )

        if query_days:
            check_influx_connection()

        for range_start, range_end in contiguous_day_ranges(query_days):
            query_end = range_end + timedelta(days=1)
            logger.info(
                f"Querying raw SCADA {range_start} through {range_end} "
                f"for {RAW_SIGNAL_COLUMNS}"
            )
            raw_period = fetch_with_retry(
                "InfluxDB turbine channels",
                fetch_influx_measurements_utc_15min,
                range_start.isoformat(),
                query_end.isoformat(),
                RAW_SIGNAL_COLUMNS,
            )

            for day in days_inclusive(range_start, range_end):
                raw_day = extract_raw_day(raw_period, day)
                destination = raw_scada_file(day)
                atomic_write_parquet(raw_day, destination)
                logger.info(f"Saved raw SCADA before analysis: {destination}")

                problems = validate_raw_day(raw_day, day)
                if problems:
                    raise ValueError(
                        f"Raw SCADA validation failed for {day}: {', '.join(problems)}"
                    )

        touched_days: set[date] = set()

        for day in days:
            raw_file = raw_scada_file(day)
            if not raw_day_is_usable(raw_file, day):
                raise ValueError(f"No usable raw SCADA partition is available for {day}")

            # The durable raw source is published before any derived analysis.
            if upload:
                upload_file_to_blob(raw_file, raw_scada_blob(day))

            raw = pd.read_parquet(raw_file)
            processed = process_raw_scada(raw)
            processed_file = processed_scada_file(day)
            atomic_write_parquet(processed, processed_file)

            if upload:
                upload_file_to_blob(processed_file, processed_scada_blob(day))

            summary = scada_quality_summary(processed)
            logger.info(f"Processed SCADA {day}: {summary}")

            enriched_file = enrich_market_day(day, processed)
            if enriched_file is None:
                logger.warning(
                    f"Market daily file is not available for {day}; raw and processed "
                    "SCADA remain cached for a later run"
                )
                continue

            touched_days.add(day)
            logger.info(f"Enriched market daily file: {enriched_file}")

        touched_months = {(day.year, day.month) for day in touched_days}
        touched_years = {day.year for day in touched_days}

        for year, month in sorted(touched_months):
            monthly_file = rebuild_month(year, month)
            if upload:
                upload_file_to_blob(
                    monthly_file, f"monthly/{year}/{monthly_file.name}"
                )

        for year in sorted(touched_years):
            ytd_file = rebuild_ytd(year)
            if upload:
                upload_file_to_blob(ytd_file, f"exports/{year}_ytd.csv")

        logger.info(f"SCADA-enriched days: {sorted(touched_days)}")
        return touched_days
