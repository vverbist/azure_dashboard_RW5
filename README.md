# RW5 Revenue Dashboard

FastAPI backend plus a buildless static JS frontend: `api/main.py` serves `frontend/`.

The shared calculation and data-preparation code lives in `app_core/`.

## Roadmap

The prioritized improvement plan, acceptance criteria, and open product
decisions are maintained in [`docs/roadmap.md`](docs/roadmap.md).

## Environment Variables

Required when loading from Azure Blob Storage:

- `AZURE_STORAGE_CONNECTION_STRING`
- `AZURE_CONTAINER_NAME` optional, defaults to `rw5data-turbine-edmij-entsoe`

Pipeline-only variables remain compatible with the existing data update script:

- `EDMIJ_USERNAME`
- `EDMIJ_PASSWORD`
- `EVIEW_USERNAME`
- `EVIEW_PASSWORD`
- `ENTSOE_TOKEN`

The manual turbine SCADA update additionally uses:

- `IDB_URL`
- `IDB_TOKEN`
- `IDB_ORG`
- `IDB_BUCKET`

## Manual SCADA Update

Connect the turbine in eCatcher, then run:

```bash
uv run python pipeline/run_scada_update.py
```

The command checks the previous 14 completed Amsterdam calendar days. It
restores raw partitions from Azure when possible, queries InfluxDB only for
missing days, uploads raw data before analysis, enriches available market daily
files, and rebuilds affected monthly/YTD exports.

Preview local coverage without network calls or file changes:

```bash
uv run python pipeline/run_scada_update.py --dry-run
```

Use `--refresh` to deliberately replace cached SCADA for the selected window,
or `--no-upload` for a local-only test run.

An existing multi-day cache with the five direct ENERCON signals can be
partitioned and published without querying InfluxDB:

```bash
uv run python pipeline/import_scada_cache.py --source data/scada/scada_h1_2026.parquet --start 2026-01-01 --end 2026-06-30
```

## Install

```bash
pip install -r requirements.txt
```

## Run the FastAPI Backend and Frontend Locally

```bash
uvicorn api.main:app --reload
```

Open:

- Frontend: `http://127.0.0.1:8000/`
- API docs: `http://127.0.0.1:8000/docs`

## Azure Startup for FastAPI plus Frontend

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

The frontend is a buildless static app in `frontend/`. FastAPI serves `frontend/index.html` and `frontend/static/*`, so the app needs only the one Uvicorn startup command in Azure.

## FastAPI Endpoints

- `GET /api/datasets`
- `GET /api/dashboard` (bundled payload used by the frontend)
- `GET /api/summary`
- `GET /api/monthly`
- `GET /api/revenue-bridge`
- `GET /api/greenchoice-bridge`
- `GET /api/strike-exposure`
- `GET /api/timeseries`
- `GET /api/anomalies`
- `GET /api/data-quality`
- `GET /api/downloads/filtered-data`
- `GET /api/downloads/summary-table`
- `GET /api/downloads/variance-table`
- `GET /api/downloads/monthly-kpi-overview`
- `GET /api/downloads/monthly-numeric`
- `GET /api/downloads/anomalies/{anomaly_type}`

Common query parameters include `dataset`, `timestamp_col`, `start_date`, `end_date`, `resampling_rule`, `greenchoice_afslag_percentage`, `greenchoice_afslag_floor`, `gvo_value`, `strike_price`, `row_count`, and `chart_group`.

## Shared Python Logic

Refactored calculation areas:

- Metadata and formatting: `app_core/metadata.py`, `app_core/formatting.py`
- Azure Blob loading: `app_core/storage.py`
- Summary and variance calculations: `app_core/calculations.py`
- Greenchoice and strike diagnostics: `app_core/benchmarks.py`
- Anomaly tables: `app_core/anomalies.py`
- Monthly KPI tables: `app_core/monthly.py`
- Data quality checks: `app_core/quality.py`
- API/chart-ready payload helpers: `app_core/chart_data.py`, `app_core/dashboard.py`

## Tests and Validation

Run unit tests:

```bash
pytest
```

Run a representative CSV validation without the API:

```bash
python scripts/validate_shared_calculations.py data/exports/2026_ytd.csv
```

## Known Limitations

- The frontend is a buildless static frontend, not SvelteKit. This avoids adding a Node build chain and keeps Azure hosting to one FastAPI startup command.
- Dataset snapshots are process-local. Running multiple Uvicorn workers gives each worker
  its own bounded cache.

## Phase 2 runtime controls

The defaults target the current B1 Linux App Service and low concurrency:

- `DATASET_CACHE_MAX_SNAPSHOTS=4`
- `DATASET_CACHE_MAX_BYTES=268435456` (256 MiB)
- `DATASET_CATALOG_TTL_SECONDS=60`
- `DASHBOARD_CHART_POINT_BUDGET=2000`
- `DASHBOARD_MAX_DATE_RANGE_DAYS=730`
- `DASHBOARD_MAX_CONCURRENT_COMPUTATIONS=2`

Snapshots are loaded lazily and replaced only after a new ETag version downloads and
parses successfully. A failed replacement remains visible as an error and does not evict
the previous valid cached snapshot. Plotly's strict 2.35.2 bundle and Montserrat are
pinned and served locally so the browser can use a same-origin Content Security Policy
without permitting dynamic JavaScript evaluation.
