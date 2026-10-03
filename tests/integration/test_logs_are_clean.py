"""Q-S6: nothing sensitive reaches the logs. Passwords, tokens, patient names and question text must never appear,
even at INFO, across a sign-in, a failed sign-in and a question to the assistant (SEC-10, NFR-06)."""

import re

import pytest
from fastapi.testclient import TestClient

from medynium_api.core.security.ratelimit import ask_limiter, login_limiter
from medynium_api.main import app
from tests.integration.test_auth_flow import CLIENT, password_for
from tests.integration.test_dashboard import signed_in

pytestmark = pytest.mark.snowflake
QUESTION = "what are her current medications, and is anything unusual about the kidney results?"
WRONG_PASSWORD = "definitely-the-wrong-password"


def test_logs_hold_no_secrets_names_or_question_text(
    users: dict, capfd: pytest.CaptureFixture[str]
) -> None:
    login_limiter.reset()
    ask_limiter.reset()
    TestClient(app, headers=CLIENT).post(
        "/auth/login", json={"email": "sharma@demo.medynium", "password": WRONG_PASSWORD}
    )
    client = signed_in("sharma@demo.medynium")
    token = client.cookies.get("med_access") or ""
    reply = client.post(
        "/copilot/ask",
        json={"question": QUESTION, "screen": "patient", "patient_id": "P-1042"},
        headers={"Accept": "application/json"},
    )
    assert reply.status_code == 200
    client.get("/patients/P-1042")
    client.get("/patients/P-9999")

    captured = capfd.readouterr()
    logs = (captured.out + captured.err).lower()
    assert logs.strip(), "expected some log output to check"
    for secret in (
        WRONG_PASSWORD,
        password_for("sharma@demo.medynium").lower(),
        token.lower(),
        "rahul patel",
        QUESTION[:30],
    ):
        assert secret and secret not in logs, f"found sensitive text in the logs: {secret[:12]}..."
    assert not re.search(r"eyj[a-z0-9_-]{10,}\.", logs), "a JWT appears in the logs"
    assert "password_hash" not in logs and "$argon2" not in logs
