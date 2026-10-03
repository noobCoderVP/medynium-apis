"""Contract tests that need no Snowflake: public routes, 401 without a session, the error shape, OpenAPI."""

import pytest
from fastapi.testclient import TestClient

from medynium_api.main import app

client = TestClient(app, headers={"X-Medynium-Client": "web"})

PROTECTED = [
    ("GET", "/me"),
    ("POST", "/auth/password"),
    ("GET", "/dashboard"),
    ("GET", "/patients"),
    ("GET", "/patients/P-1042"),
    ("GET", "/patients/P-1042/medications"),
    ("GET", "/patients/P-1042/labs"),
    ("GET", "/patients/P-1042/timeline"),
    ("GET", "/patients/P-1042/labs/eGFR/trend"),
    ("GET", "/patients/P-1042/claims"),
    ("GET", "/patients/P-1042/notes"),
    ("GET", "/patients/P-1042/pins"),
    ("POST", "/patients/P-1042/pins"),
    ("GET", "/patients/P-1042/findings"),
    ("POST", "/patients/P-1042/findings"),
    ("GET", "/patients/P-1042/colleagues"),
    ("PATCH", "/findings/FND-1"),
    ("GET", "/audit"),
    ("GET", "/views"),
    ("POST", "/views/preview"),
    ("GET", "/admin/users"),
    ("GET", "/admin/invites"),
    ("POST", "/patients/P-1042/share"),
    ("POST", "/admin/invites"),
    ("GET", "/health/details"),
]

NOT_FOUND = {"error": "not_found", "message": "The requested resource was not found."}


def test_health_is_public_and_minimal() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert set(response.json()) == {"status", "version"}


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_routes_need_a_session(method: str, path: str) -> None:
    response = client.request(method, path, json={} if method == "POST" else None)
    assert response.status_code == 401, (method, path, response.text)
    assert response.json()["error"] == "unauthorized"


def test_unknown_route_uses_the_error_contract() -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_invalid_body_uses_the_error_contract() -> None:
    response = client.post("/auth/login", json={"email": "a@b.c"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "invalid_request" and body["details"][0]["field"] == "password"


def test_state_changing_requests_need_the_client_header() -> None:
    response = TestClient(app).post("/auth/login", json={"email": "a@b.c", "password": "x"})
    assert response.status_code == 403 and response.json()["error"] == "forbidden"


def test_responses_are_not_cached() -> None:
    assert client.get("/me").headers["cache-control"] == "private, no-store"
    assert "cache-control" not in client.get("/health").headers


def test_openapi_documents_every_endpoint() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    expected = {
        "/auth/login", "/auth/refresh", "/auth/logout", "/auth/password", "/me", "/auth/invites/{token}",
        "/auth/invites/accept", "/admin/invites", "/admin/invites/{invite_id}", "/admin/users",
        "/admin/users/{user_id}", "/admin/users/{user_id}/reset-password",
        "/admin/users/{user_id}/entitlements", "/dashboard", "/patients", "/patients/{patient_id}",
        "/patients/{patient_id}/medications", "/patients/{patient_id}/labs",
        "/patients/{patient_id}/labs/{code}/trend", "/patients/{patient_id}/timeline",
        "/patients/{patient_id}/claims", "/patients/{patient_id}/notes",
        "/patients/{patient_id}/notes/{note_id}", "/patients/{patient_id}/pins",
        "/patients/{patient_id}/pins/{pin_id}", "/audit", "/views/preview", "/views", "/health",
        "/health/details",
    }  # fmt: skip
    assert expected <= set(paths), expected - set(paths)
