"""Read the signed-in user from Azure App Service Authentication ("Easy Auth").

When Easy Auth is enabled, the platform authenticates the request and injects the user's
identity as request headers (and strips any client-supplied copies), so these are
trustworthy as long as the app is only reachable through the platform gate. Locally, or
if the gate is off, the headers are absent and `current_user` returns None.

This module is for surfacing "who is signed in" and optional defense-in-depth; the actual
access gate is the App Service Authentication configuration, not application code.
"""
from __future__ import annotations

import base64
import binascii
import json

_NAME_HEADER = "x-ms-client-principal-name"
_ID_HEADER = "x-ms-client-principal-id"
_IDP_HEADER = "x-ms-client-principal-idp"
_PRINCIPAL_HEADER = "x-ms-client-principal"

_NAME_CLAIMS = (
    "name",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
)
_EMAIL_CLAIMS = (
    "preferred_username",
    "emails",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
)


def _decode_principal(encoded: str | None) -> dict | None:
    if not encoded:
        return None
    try:
        return json.loads(base64.b64decode(encoded))
    except (binascii.Error, ValueError, json.JSONDecodeError):
        return None


def _claim(principal: dict | None, types: tuple[str, ...]) -> str | None:
    for claim in (principal or {}).get("claims", []):
        if claim.get("typ") in types:
            return claim.get("val")
    return None


def current_user(headers) -> dict | None:
    """Return the Easy Auth identity for a request, or None when unauthenticated.

    `headers` is any case-insensitive mapping (e.g. Starlette ``request.headers``).
    """
    name = headers.get(_NAME_HEADER)
    principal = _decode_principal(headers.get(_PRINCIPAL_HEADER))
    if not name and principal is None:
        return None

    email = name or _claim(principal, _EMAIL_CLAIMS)
    display = _claim(principal, _NAME_CLAIMS) or email
    return {
        "email": email,
        "name": display,
        "id": headers.get(_ID_HEADER),
        "provider": headers.get(_IDP_HEADER),
    }
