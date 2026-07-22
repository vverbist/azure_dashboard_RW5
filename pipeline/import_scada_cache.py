# -*- coding: utf-8 -*-
"""Import a multi-day SCADA cache and publish it through the daily workflow.

The source must contain ``timestamp_utc`` plus the five direct ENERCON signals
P, PavaVWind, AbstMaxP, PSet1, and Vwind. Extra derived columns are ignored.

    uv run python pipeline/import_scada_cache.py \
        --source data/scada/scada_h1_2026.parquet \
        --start 2026-01-01 --end 2026-06-30
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from pipeline_lib import configure_logging
from scada_pipeline import partition_raw_cache, update_scada_period


logger = configure_logging("import_scada_cache")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing usable daily raw partitions",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Import and process locally without uploading to Azure",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.source.exists():
        raise FileNotFoundError(f"SCADA cache does not exist: {args.source}")

    imported = partition_raw_cache(
        args.source,
        args.start,
        args.end,
        overwrite=args.overwrite,
    )
    logger.info(
        f"Daily raw cache is ready for {args.start} through {args.end}; "
        f"wrote {len(imported)} partition(s)"
    )

    update_scada_period(
        args.start,
        args.end,
        logger=logger,
        upload=not args.no_upload,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.error(f"SCADA cache import failed: {exc}")
        sys.exit(1)
