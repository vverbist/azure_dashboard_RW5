# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Python environment: managed via [uv](https://docs.astral.sh/uv/) — `.venv` lives in the repo root, pinned to Python 3.12 (see `.python-version`). Run everything through `uv run` rather than activating the venv manually.

`pyproject.toml` + `uv.lock` are the source of truth for dependencies — edit those (`uv add <package>`), don't hand-edit `requirements.txt`. `requirements.txt` only exists because Azure App Service's Oryx build reads it directly; after changing dependencies, regenerate it with:

```bash
uv export --format requirements.txt --no-hashes -o requirements.txt
```

```bash
uv sync --extra test

# FastAPI + static JS app
uv run uvicorn api.main:app --reload
# Frontend: http://127.0.0.1:8000/  API docs: http://127.0.0.1:8000/docs

# Tests (exercise app_core business logic directly, no FastAPI/Azure needed)
uv run pytest
uv run pytest tests/test_shared_calculations.py::test_summary_table_calculation  # single test

# Validate shared calculations against a real CSV export
uv run python scripts/validate_shared_calculations.py data/exports/2026_ytd.csv
```

A `.claude/launch.json` entry named `fastapi` should point at `.venv\Scripts\python.exe` in the repo root.

### Environment variables (`.env`, see `.env.example`)

- `AZURE_STORAGE_CONNECTION_STRING`, `AZURE_CONTAINER_NAME` — required to read blob data.
- `EDMIJ_USERNAME`/`PASSWORD`, `EVIEW_USERNAME`/`PASSWORD`, `ENTSOE_TOKEN` — only needed by `pipeline/`, not the dashboard.

## Architecture

Single app: `api/main.py` mounts `api/routes/*` under `/api` and serves `frontend/` as static files — no bundler/Node build step; the frontend loads via a single `<script type="module">` entry (`frontend/static/app.js` → `frontend/static/dashboard/main.js`) and charts render with Plotly from a CDN.

`frontend/index.html` cache-busts `styles.css` and `main.js` with a `?v=` query string — bump it whenever either file changes, or the browser will keep serving the old cached copy across reloads.

`app_core/` holds the shared calculation/data-prep code, called by the API routes:

- `storage.py` — Azure Blob read/list.
- `calculations.py` / `benchmarks.py` — summary/variance tables, Greenchoice and strike-price diagnostics.
- `anomalies.py`, `monthly.py`, `quality.py` — anomaly event grouping, monthly KPI tables, data-quality checks.
- `chart_data.py` / `dashboard.py` — shape prepared frames into API/chart-ready payloads (`prepare_dashboard_frames`, bridge components, timeseries).
- `metadata.py`, `formatting.py`, `serialization.py` — column metadata/labels, display formatting, JSON-safe serialization (`to_jsonable`).

API request flow: every route in `api/routes/` depends on `dashboard_query()` in `api/routes/_common.py`, which parses query params into a `DashboardSettings` object and resolves the dataset (defaults to the latest `exports/*.csv` blob if none given). `load_prepared_frames()` then does blob read → `prepare_dashboard_frames()` (filter/resample/diagnostics) → the route's specific calculation function → JSON via `clean_items`/`to_jsonable`, or a CSV `Response` for `/api/downloads/*`.

Known limitation: the FastAPI app re-reads and re-parses the Azure blob CSV on every request — there is no server-side caching layer yet.

`pipeline/` is a separate, standalone data-ingestion script (EDMIJ nominations + E-View delivered volumes + ENTSO-E prices → daily parquet → monthly/YTD CSV → upload back to the same Azure blob container that the dashboards read from). It is not wired in as a proper package yet (no `__init__.py`, imports its `config.py` as a bare module) and is not part of the dashboard app's runtime.
