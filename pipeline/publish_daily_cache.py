# -*- coding: utf-8 -*-
"""One-time publication of the existing local market daily cache to Azure.

This seeds Azure as the canonical source so a fresh checkout can reconstruct its
local cache without copying ``data/`` between machines.

    uv run python pipeline/publish_daily_cache.py
    uv run python pipeline/publish_daily_cache.py --start 2026-01-01 --end 2026-08-23
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from azure_sync import (
    day_from_market_blob,
    list_market_daily_blobs,
    upload_market_daily_file,
)
from config import validate_required_vars
from pipeline_lib import configure_logging
from scada_pipeline import pipeline_update_lock


logger = configure_logging("publish_daily_cache")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, help="First day (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat, help="Last day (YYYY-MM-DD)")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace daily partitions that already exist in Azure",
    )
    return parser.parse_args()


def selected_local_partitions(start: date | None, end: date | None):
    from config import DAILY_DIR

    for file in sorted(DAILY_DIR.glob("*/*.parquet")):
        day = day_from_market_blob(f"daily/{file.parent.name}/{file.name}")
        if day is None:
            continue
        if start is not None and day < start:
            continue
        if end is not None and day > end:
            continue
        yield day, file


def main():
    args = parse_args()
    if args.start and args.end and args.start > args.end:
        raise ValueError("--start must not be after --end")

    validate_required_vars(
        ["AZURE_STORAGE_CONNECTION_STRING", "AZURE_CONTAINER_NAME"]
    )
    local = list(selected_local_partitions(args.start, args.end))
    if not local:
        raise FileNotFoundError("No local market daily partitions were selected")

    with pipeline_update_lock(logger=logger):
        remote_days = set(list_market_daily_blobs())
        uploaded = 0
        skipped = 0

        for day, file in local:
            if day in remote_days and not args.overwrite:
                skipped += 1
                continue
            upload_market_daily_file(file, day, overwrite=args.overwrite)
            uploaded += 1

    logger.info(
        f"Daily cache publication complete: uploaded {uploaded}, skipped {skipped}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.error(f"Daily cache publication failed: {exc}")
        sys.exit(1)
