import base64
import json

from app_core.auth import current_user


def _principal_header(claims: list[dict]) -> str:
    return base64.b64encode(json.dumps({"claims": claims}).encode()).decode()


def test_current_user_from_name_header():
    user = current_user({"x-ms-client-principal-name": "vverbist@hy-gro.nl"})

    assert user["email"] == "vverbist@hy-gro.nl"
    assert user["name"] == "vverbist@hy-gro.nl"


def test_current_user_prefers_display_name_from_claims():
    header = _principal_header([
        {"typ": "name", "val": "Victor Verbist"},
        {"typ": "preferred_username", "val": "vverbist@hy-gro.nl"},
    ])

    user = current_user({"x-ms-client-principal": header})

    assert user["name"] == "Victor Verbist"
    assert user["email"] == "vverbist@hy-gro.nl"


def test_current_user_none_when_unauthenticated():
    assert current_user({}) is None


def test_current_user_ignores_malformed_principal():
    assert current_user({"x-ms-client-principal": "not-valid-base64-json"}) is None
