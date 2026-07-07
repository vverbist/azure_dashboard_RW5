# RW5 Revenue Dashboard

FastAPI backend plus a buildless static JS frontend: `api/main.py` serves `frontend/`.

The shared calculation and data-preparation code lives in `app_core/`.

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
- Plotly in the frontend is loaded from the Plotly CDN.
- The FastAPI app reads Azure Blob data per request; server-side caching can be added later if response time becomes an issue.
