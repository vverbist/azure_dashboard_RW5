# -*- coding: utf-8 -*-
"""
Ad-hoc manual repair for a specific date range - for cases the automatic daily
repair window (see run_daily_update.py) doesn't cover, e.g. a source outage
discovered weeks later.

Examples:
    uv run python pipeline/run_repair.py --start 2026-01-01 --end 2026-06-30 --check-only
    uv run python pipeline/run_repair.py --start 2026-03-01 --end 2026-06-30
    uv run python pipeline/run_repair.py --start 2026-03-01 --end 2026-06-30 --no-upload
"""

import argparse
import sys
from datetime import date

from azure_sync import (
    market_daily_file,
    sync_market_daily_cache,
    upload_market_daily_file,
)
from config import MARKET_REQUIRED_VARS, validate_required_vars
from pipeline_lib import (
    configure_logging,
    rebuild_month,
    rebuild_ytd,
    report_nan_timestamps_for_period,
    repair_nan_timestamps_for_period,
    upload_file_to_blob,
)
from scada_pipeline import pipeline_update_lock

logger = configure_logging("run_repair")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument(
        "--check-only", action="store_true",
        help="Only report NaNs, don't fetch/patch anything",
    )
    parser.add_argument(
        "--export-csv", action="store_true",
        help="Export the NaN report to data/exports/nan_report_<start>_<end>.csv",
    )
    parser.add_argument(
        "--no-upload", action="store_true",
        help="Rebuild monthly/YTD exports locally but skip uploading to blob storage",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    validate_required_vars(MARKET_REQUIRED_VARS)

    with pipeline_update_lock(logger=logger):
        remote_days = sync_market_daily_cache(
            years=set(range(args.start.year, args.end.year + 1)),
            logger=logger,
        )
        if not remote_days:
            raise RuntimeError(
                "Azure has no canonical market daily partitions for the selected "
                "period. Seed them first with pipeline/publish_daily_cache.py"
            )

        report_nan_timestamps_for_period(
            args.start,
            args.end,
            export_csv=args.export_csv,
        )

        if args.check_only:
            return

        changed_days, failed_days = repair_nan_timestamps_for_period(
            args.start,
            args.end,
            rebuild_exports=False,
            upload_exports=False,
        )

        publish_failed = False
        if not args.no_upload:
            for day in sorted(changed_days):
                try:
                    upload_market_daily_file(market_daily_file(day), day)
                except Exception as exc:
                    logger.error(f"Failed to publish repaired daily file {day}: {exc}")
                    publish_failed = True

        if failed_days or publish_failed:
            logger.error(
                "Repaired daily partitions were not published completely; "
                f"aggregate exports were left unchanged. Failed days: "
                f"{sorted(failed_days)}"
            )
            sys.exit(1)

        touched_months = {(day.year, day.month) for day in changed_days}
        touched_years = {day.year for day in changed_days}

        for year, month in sorted(touched_months):
            monthly_file = rebuild_month(year, month)
            if not args.no_upload:
                upload_file_to_blob(
                    monthly_file, f"monthly/{year}/{monthly_file.name}"
                )

        for year in sorted(touched_years):
            ytd_file = rebuild_ytd(year)
            if not args.no_upload:
                upload_file_to_blob(ytd_file, f"exports/{year}_ytd.csv")


if __name__ == "__main__":
    main()
