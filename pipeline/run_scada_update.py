# -*- coding: utf-8 -*-
"""
Manual SCADA update for a short trailing window.

Connect the turbine in eCatcher before running this command. By default it
checks the previous 14 completed Europe/Amsterdam calendar days, restores raw
partitions from Azure when available, and queries InfluxDB only for missing
days. Raw SCADA is saved and uploaded before analysis or market enrichment.

    uv run python pipeline/run_scada_update.py
    uv run python pipeline/run_scada_update.py --dry-run
    uv run python pipeline/run_scada_update.py --refresh
    uv run python pipeline/run_scada_update.py --no-upload
"""

import argparse
import sys
from datetime import date, timedelta

from pipeline_lib import configure_logging
from scada_pipeline import update_scada_period


DEFAULT_LOOKBACK_DAYS = 14
logger = configure_logging("run_scada_update")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=f"Completed local calendar days to inspect (default: {DEFAULT_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        help="Last local calendar day to inspect (YYYY-MM-DD; default: yesterday)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-query every selected day even when raw SCADA is already cached",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report local coverage without querying InfluxDB or changing files",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Write and rebuild locally without uploading any files to Azure",
    )
    return parser.parse_args()


def selected_window(end_day: date, lookback_days: int) -> tuple[date, date]:
    if lookback_days < 1:
        raise ValueError("--lookback-days must be at least 1")
    return end_day - timedelta(days=lookback_days - 1), end_day


def main():
    args = parse_args()
    end_day = args.end or (date.today() - timedelta(days=1))
    start_day, end_day = selected_window(end_day, args.lookback_days)

    update_scada_period(
        start_day,
        end_day,
        logger=logger,
        refresh=args.refresh,
        dry_run=args.dry_run,
        upload=not args.no_upload,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.error(f"SCADA update failed: {exc}")
        sys.exit(1)
