"""Mobile bearer mode: the same access token works as a header, CSRF accepts the mobile client. No Snowflake."""

import pytest
from fastapi.testclient import TestClient

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.security.tokens import create_access_token
from medynium_api.main import app

SETTINGS = Settings(session_secret="x" * 40)  # type: ignore[arg-type]
app.dependency_overrides[get_settings] = lambda: SETTINGS
USER = "7f0c2f2e-5b43-4a43-9a4e-2f4d0d8c1a11"


def token() -> str:
    return create_access_token(
        SETTINGS, user_id=USER, role="DOCTOR", is_admin=False, token_version=1, session_id="s1"
    )


def test_csrf_accepts_mobile_and_rejects_other_clients() -> None:
    client = TestClient(app)
    body = {"refresh": "x" * 20}
    assert client.post("/auth/mobile/refresh", json=body).status_code == 403
    assert (
        client.post(
            "/auth/mobile/refresh", json=body, headers={"X-Medynium-Client": "evil"}
        ).status_code
        == 403
    )
    # Past CSRF the token is rejected by the service (not a 403).
    other = client.post("/auth/mobile/refresh", json=body, headers={"X-Medynium-Client": "mobile"})
    assert other.status_code != 403


def test_bearer_header_is_read_as_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.requests import Request

    from medynium_api.core import session as session_module
    from medynium_api.core.session import optional_session

    monkeypatch.setattr(session_module, "get_settings", lambda: SETTINGS)

    def req(headers: list[tuple[bytes, bytes]]) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})

    session = optional_session(req([(b"authorization", f"Bearer {token()}".encode())]))
    assert session is not None and session.user_id == USER
    assert optional_session(req([(b"authorization", b"Bearer garbage")])) is None
    assert optional_session(req([(b"authorization", b"Basic abc")])) is None
    assert optional_session(req([])) is None
