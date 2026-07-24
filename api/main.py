from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import anomalies, auth, bridges, datasets, downloads, monthly, quality, scada, summary, timeseries
from app_core.auth import current_user

app = FastAPI(title="RW5 Revenue Dashboard API", version="1.0.0")

# Optional defense-in-depth behind Azure App Service Authentication (Easy Auth). The
# platform gate is the real access control; enabling REQUIRE_AUTH additionally rejects any
# /api request that arrives without an Easy Auth identity. Off by default so local dev and
# a not-yet-gated deployment keep working.
REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.middleware("http")
async def no_cache_static(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.middleware("http")
async def enforce_auth(request, call_next):
    if REQUIRE_AUTH and request.url.path.startswith("/api/") and current_user(request.headers) is None:
        return JSONResponse({"detail": "Authentication required."}, status_code=401)
    return await call_next(request)


app.include_router(auth.router, prefix="/api")
app.include_router(datasets.router, prefix="/api")
app.include_router(summary.router, prefix="/api")
app.include_router(monthly.router, prefix="/api")
app.include_router(scada.router, prefix="/api")
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
