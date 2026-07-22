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

from config import MARKET_REQUIRED_VARS, validate_required_vars
from pipeline_lib import (
    configure_logging,
    report_nan_timestamps_for_period,
    repair_nan_timestamps_for_period,
)

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
        rebuild_exports=True,
        upload_exports=not args.no_upload,
    )

    if failed_days:
        logger.error(f"Completed with failures on: {sorted(failed_days)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
