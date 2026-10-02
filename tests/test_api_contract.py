import pytest
from fastapi.testclient import TestClient

from medynium_api.main import app

client = TestClient(app)

PROTECTED = [
    ("GET", "/me"),
    ("GET", "/dashboard"),
    ("GET", "/patients"),
    ("GET", "/patients/P-1042"),
    ("GET", "/patients/P-1042/timeline"),
    ("GET", "/patients/P-1042/labs/eGFR/trend"),
    ("GET", "/patients/P-1042/claims"),
    ("POST", "/patients/P-1042/safety-review"),
    ("GET", "/evidence/ANS-0001"),
    ("GET", "/knowledge/search?q=metformin"),
    ("GET", "/audit"),
    ("POST", "/admin/golden-run"),
]


def test_health_is_public_and_has_no_secrets() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "password" not in response.text.lower()
    assert "key" not in body["snowflake"]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_routes_need_a_session(method: str, path: str) -> None:
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_unknown_route_uses_the_error_contract() -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json() == {
        "error": "not_found",
        "message": "The requested resource was not found.",
    }


def test_login_is_a_stub_until_slice_3() -> None:
    response = client.post("/auth/login", json={"username": "SHARMA_DR", "password": "x"})
    assert response.status_code == 501
    assert response.json()["error"] == "not_implemented"


def test_openapi_documents_every_srs_endpoint() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    expected = {
        "/auth/login", "/auth/logout", "/me", "/dashboard", "/dashboard/briefing", "/patients",
        "/patients/{patient_id}", "/patients/{patient_id}/timeline",
        "/patients/{patient_id}/labs/{code}/trend", "/patients/{patient_id}/claims",
        "/patients/{patient_id}/safety-review", "/copilot/ask", "/agent/actions",
        "/evidence/{answer_id}", "/knowledge/search", "/views/preview", "/views", "/audit",
        "/admin/golden-run", "/admin/skills/{name}", "/health",
    }  # fmt: skip
    assert expected <= set(paths)
