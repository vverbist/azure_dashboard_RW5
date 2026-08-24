# Machine-independent pipeline

Azure Blob Storage is the canonical store for daily market data, SCADA data,
monthly exports, and YTD exports. A machine's local `data/` directory is a
rebuildable cache after the initial migration below.

## One-time migration

Run this once on the machine that currently has the complete `data/daily`
history:

```powershell
uv run python pipeline/publish_daily_cache.py
```

The command validates every daily parquet file and uploads only partitions that
do not already exist in Azure. Use `--overwrite` only when deliberately replacing
existing canonical partitions.

Daily and SCADA updates refuse to publish aggregate exports until Azure contains
canonical daily market partitions. This prevents a fresh machine's short local
backfill from replacing the complete YTD export.

## Running from another machine

The machine needs the repository, its Python environment, and a configured
`.env`. It does not need a copied `data/` directory.

Daily market update:

```powershell
.\update_daily_data.bat
```

SCADA update after connecting eCatcher:

```powershell
.\update_scada_data.bat
```

At the start of either update, the selected Azure daily history is downloaded
into `data/daily`. Changed daily partitions are uploaded before monthly and YTD
exports are rebuilt and published.

## Azure layout

```text
daily/YYYY/YYYY-MM-DD.parquet
scada/raw/YYYY/YYYY-MM-DD.parquet
scada/processed/YYYY/YYYY-MM-DD.parquet
monthly/YYYY/YYYY-MM.csv
exports/YYYY_ytd.csv
locks/pipeline-update.lock
```

The lock blob uses a renewable Azure lease. The existing local lock remains in
place as a second guard. Together they prevent daily, repair, and SCADA writers
on different machines from publishing concurrently.

Keep only one scheduled daily updater enabled. Other configured machines can be
used for manual runs or as replacements without copying pipeline data.
