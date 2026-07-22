# -*- coding: utf-8 -*-
"""
Daily entry point: syncs forward from the last synced day, re-checks a trailing
window for NaNs/late corrections, then rebuilds and uploads any touched
monthly/YTD exports.

    uv run python pipeline/run_daily_update.py
"""

import sys
from datetime import date, timedelta

from config import (
    DAILY_REPAIR_LOOKBACK_DAYS,
    MARKET_REQUIRED_VARS,
    MAX_BACKFILL_LOOKBACK_DAYS,
    validate_required_vars,
)
from pipeline_lib import (
    configure_logging,
    find_last_synced_day,
    backfill_days,
    repair_nan_timestamps_for_period,
    rebuild_month,
    rebuild_ytd,
    upload_file_to_blob,
)
from scada_pipeline import pipeline_update_lock

logger = configure_logging("run_daily_update")


def determine_sync_window(today: date) -> tuple[date, date]:
    yesterday = today - timedelta(days=1)
    last_synced = find_last_synced_day()

    if last_synced is None:
        start_day = yesterday - timedelta(days=MAX_BACKFILL_LOOKBACK_DAYS)
    else:
        start_day = last_synced + timedelta(days=1)

    return start_day, yesterday


def main():
    logger.info("Starting daily market data update")
    validate_required_vars(MARKET_REQUIRED_VARS)

    with pipeline_update_lock():
        run_locked_update()


def run_locked_update():
    """Run the existing market update while holding the shared writer lock."""

    today = date.today()
    start_day, yesterday = determine_sync_window(today)

    if start_day > yesterday:
        logger.info("Already up to date, nothing to backfill")
        start_day = yesterday + timedelta(days=1)

    logger.info(f"Backfilling missing daily files from {start_day} to {yesterday}")
    backfill_failed = backfill_days(start_day, yesterday, overwrite=False)

    repair_start = min(start_day, yesterday - timedelta(days=DAILY_REPAIR_LOOKBACK_DAYS - 1))
    logger.info(f"Checking/repairing NaNs from {repair_start} to {yesterday}")

    changed_days, repair_failed = repair_nan_timestamps_for_period(
        repair_start,
        yesterday,
        rebuild_exports=False,
        upload_exports=False,
    )

    touched_days = set(changed_days)
    d = start_day
    while d <= yesterday:
        touched_days.add(d)
        d += timedelta(days=1)

    touched_months = {(d.year, d.month) for d in touched_days}
    touched_years = {d.year for d in touched_days}

    export_failed = False

    for year, month in sorted(touched_months):
        try:
            monthly_file = rebuild_month(year, month)
            upload_file_to_blob(monthly_file, f"monthly/{year}/{monthly_file.name}")
        except Exception as exc:
            logger.error(f"Failed to rebuild/upload monthly {year}-{month:02d}: {exc}")
            export_failed = True

    for year in sorted(touched_years):
        try:
            ytd_file = rebuild_ytd(year)
            upload_file_to_blob(ytd_file, f"exports/{year}_ytd.csv")
        except Exception as exc:
            logger.error(f"Failed to rebuild/upload YTD {year}: {exc}")
            export_failed = True

    failed_days = sorted(set(backfill_failed) | set(repair_failed))

    if failed_days or export_failed:
        logger.error(f"Completed with failures. Failed days: {failed_days}")
        sys.exit(1)

    logger.info("Done")


if __name__ == "__main__":
    main()
