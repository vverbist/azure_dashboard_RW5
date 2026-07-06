from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import anomalies, bridges, datasets, downloads, monthly, quality, summary, timeseries

app = FastAPI(title="RW5 Revenue Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(datasets.router, prefix="/api")
app.include_router(summary.router, prefix="/api")
app.include_router(monthly.router, prefix="/api")
app.include_router(bridges.router, prefix="/api")
app.include_router(timeseries.router, prefix="/api")
app.include_router(anomalies.router, prefix="/api")
app.include_router(quality.router, prefix="/api")
app.include_router(downloads.router, prefix="/api")

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"
ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.get("/", include_in_schema=False)
def serve_frontend():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "RW5 Revenue Dashboard API", "docs": "/docs"}


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend_route(full_path: str):
    index = FRONTEND_DIR / "index.html"
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    if index.exists() and not full_path.startswith("api/"):
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Not found")
