from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import (
    anomalies,
    auth,
    bridges,
    dashboard,
    datasets,
    downloads,
    monthly,
    quality,
    scada,
    summary,
    timeseries,
)
from app_core.auth import current_user

app = FastAPI(title="RW5 Revenue Dashboard API", version="2.0.0")


def _boolean_setting(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# Easy Auth remains the platform access gate. On Azure, application-level verification is
# secure by default; local development stays open unless REQUIRE_AUTH is explicitly set.
REQUIRE_AUTH = _boolean_setting(
    "REQUIRE_AUTH",
    default=bool(os.getenv("WEBSITE_SITE_NAME")),
)

@app.middleware("http")
async def secure_requests(request, call_next):
    if REQUIRE_AUTH and request.url.path.startswith("/api/") and current_user(request.headers) is None:
        response = JSONResponse({"detail": "Authentication required."}, status_code=401)
    else:
        response = await call_next(request)

    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"

    content_type = response.headers.get("content-type", "")
    path = request.url.path
    if path.startswith("/static/vendor/") or path.startswith("/static/fonts/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.startswith("/static/") or content_type.startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache"
    elif path.startswith("/api/") and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    return response


app.add_middleware(GZipMiddleware, minimum_size=1_000, compresslevel=5)


app.include_router(auth.router, prefix="/api")
app.include_router(datasets.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
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
