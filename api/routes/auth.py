from __future__ import annotations

from fastapi import APIRouter, Request

from app_core.auth import current_user

router = APIRouter()


@router.get("/me")
def get_me(request: Request):
    """Report the signed-in user injected by Azure App Service Authentication.

    Returns `authenticated: false` when the request has no Easy Auth identity (e.g. local
    development without the platform gate)."""
    user = current_user(request.headers)
    return {"authenticated": user is not None, "user": user}
