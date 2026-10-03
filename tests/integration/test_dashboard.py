"""Dashboard widgets equal their ground truth and are scoped per user (FR-17, B-4)."""

import pytest
from fastapi.testclient import TestClient

from medynium_api.core.security.ratelimit import login_limiter
from medynium_api.main import app
from tests.integration.test_auth_flow import CLIENT, password_for

pytestmark = pytest.mark.snowflake


def signed_in(email: str) -> TestClient:
    login_limiter.reset()
    client = TestClient(app, headers=CLIENT)
    assert (
        client.post(
            "/auth/login", json={"email": email, "password": password_for(email)}
        ).status_code
        == 200
    )
    return client


def test_doctor_dashboard_matches_ground_truth(users: dict) -> None:
    body = signed_in("sharma@demo.medynium").get("/dashboard").json()
    assert body["as_of"] == "2026-10-02"
    assert body["utilization"]["patients"] == 157
    ids = [w["patient_id"] for w in body["worklist"]]
    assert "P-1042" in ids
    s1 = next(w for w in body["worklist"] if w["patient_id"] == "P-1042")
    labels = [f["label"] for f in s1["flags"]]
    assert "ED visit 2 Oct" in labels and any("new lab" in label for label in labels)
    assert s1["last_encounter"]["kind"] == "EMERGENCY"
    labs = body["recent_changes"]["labs"]
    assert 0 < len(labs) <= 10
    assert all(c["latest"] is not None and c["date"] <= "2026-10-02" for c in labs)
    assert body["recent_changes"]["medications"]


def test_assistant_dashboard_excludes_s3_everywhere(users: dict) -> None:
    body = signed_in("assistant@demo.medynium").get("/dashboard").json()
    assert body["utilization"]["patients"] == 36
    everything = str(body)
    assert "P-1093" not in everything and "Amit Kumar" not in everything


def test_second_doctor_never_sees_sharmas_patients(users: dict) -> None:
    body = signed_in("second.doctor@demo.medynium").get("/dashboard").json()
    assert "P-1042" not in str(body)
    assert body["utilization"]["patients"] == 150


def test_dashboard_requires_a_session() -> None:
    assert TestClient(app).get("/dashboard").status_code == 401


def test_briefing_is_scoped_and_needs_a_session(users: dict) -> None:
    body = signed_in("assistant@demo.medynium").get("/dashboard/briefing").json()
    assert body["items"] and "P-1093" not in str(body) and "Amit Kumar" not in str(body)
    assert all(i["tag"] == "patient_fact" for i in body["items"])
    assert TestClient(app).get("/dashboard/briefing").status_code == 401
