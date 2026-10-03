"""Sign-in, refresh rotation, reuse detection, logout, CSRF and cache headers against the live account."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from medynium_api.core.security.ratelimit import login_limiter
from medynium_api.main import app

pytestmark = pytest.mark.snowflake
CREDENTIALS = Path.home() / ".medynium" / "demo_credentials.txt"
CLIENT = {"X-Medynium-Client": "web"}


def password_for(email: str) -> str:
    if not CREDENTIALS.exists():
        pytest.skip("demo credentials not found")
    pairs = dict(line.split(" ", 1) for line in CREDENTIALS.read_text().splitlines() if " " in line)
    return pairs[email]


@pytest.fixture
def client() -> TestClient:
    login_limiter.reset()
    return TestClient(app, headers=CLIENT)


def sign_in(client: TestClient, email: str = "sharma@demo.medynium") -> None:
    response = client.post("/auth/login", json={"email": email, "password": password_for(email)})
    assert response.status_code == 200, response.text


def test_login_sets_httponly_cookies_and_me_works(client: TestClient, users: dict) -> None:
    response = client.post(
        "/auth/login",
        json={"email": "sharma@demo.medynium", "password": password_for("sharma@demo.medynium")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["role"] == "DOCTOR" and body["user"]["is_admin"] is True
    cookies = response.headers.get_list("set-cookie")
    assert any(
        c.startswith("med_access=") and "HttpOnly" in c and "SameSite=lax" in c for c in cookies
    )
    assert any(c.startswith("med_refresh=") and "Path=/auth" in c for c in cookies)
    me = client.get("/me")
    assert me.status_code == 200
    assert me.json()["patient_count"] == 157
    assert "admin:users" in me.json()["permissions"]
    assert me.headers["cache-control"] == "private, no-store"


def test_wrong_password_and_unknown_email_look_identical(client: TestClient, users: dict) -> None:
    wrong = client.post("/auth/login", json={"email": "sharma@demo.medynium", "password": "x" * 14})
    unknown = client.post(
        "/auth/login", json={"email": "nobody@demo.medynium", "password": "x" * 14}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert (
        wrong.json()
        == unknown.json()
        == {"error": "unauthorized", "message": "Email or password is incorrect."}
    )


def test_state_changing_requests_need_the_client_header(users: dict) -> None:
    bare = TestClient(app)
    response = bare.post("/auth/login", json={"email": "a@b.c", "password": "x"})
    assert response.status_code == 403 and response.json()["error"] == "forbidden"


def test_refresh_rotates_and_reuse_revokes_the_session(client: TestClient, users: dict) -> None:
    sign_in(client)
    first_refresh = client.cookies.get("med_refresh", path="/auth")
    assert first_refresh
    assert client.post("/auth/refresh").status_code == 204
    second_refresh = client.cookies.get("med_refresh", path="/auth")
    assert second_refresh and second_refresh != first_refresh
    assert client.get("/me").status_code == 200

    # Replay the already-rotated token: the whole session must end.
    thief = TestClient(app, headers=CLIENT)
    thief.cookies.set("med_refresh", first_refresh, path="/auth")
    assert thief.post("/auth/refresh").status_code == 401
    legit = TestClient(app, headers=CLIENT)
    legit.cookies.set("med_refresh", second_refresh, path="/auth")
    assert legit.post("/auth/refresh").status_code == 401


def test_logout_revokes_the_session(client: TestClient, users: dict) -> None:
    sign_in(client, "assistant@demo.medynium")
    refresh = client.cookies.get("med_refresh", path="/auth")
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/me").status_code == 401
    replay = TestClient(app, headers=CLIENT)
    replay.cookies.set("med_refresh", refresh, path="/auth")
    assert replay.post("/auth/refresh").status_code == 401


def test_protected_route_without_a_session_is_401(client: TestClient) -> None:
    assert client.get("/me").status_code == 401
