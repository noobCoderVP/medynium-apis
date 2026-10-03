"""Invitations, accounts, lockout, entitlements, disable and reset with real accounts (B-2, B-3)."""

import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from medynium_api.core.security.ratelimit import login_limiter
from medynium_api.main import app
from tests.integration.test_auth_flow import CLIENT
from tests.integration.test_dashboard import signed_in

pytestmark = pytest.mark.snowflake
S3 = "P-1093"
GOOD = "correct-horse-battery-9"


def token_of(accept_url: str) -> str:
    return parse_qs(urlparse(accept_url).query)["token"][0]


@pytest.fixture
def admin(users: dict) -> TestClient:
    return signed_in("sharma@demo.medynium")


def invite_and_accept(admin: TestClient, users: dict, patient_ids: list[str]) -> tuple[str, dict]:
    email = f"test.{secrets.token_hex(4)}@demo.medynium"
    created = admin.post(
        "/admin/invites",
        json={"email": email, "display_name": "Test Assistant", "role": "ASSISTANT",
              "supervising_doctor_id": users["sharma"]["user_id"], "patient_ids": patient_ids},
    )  # fmt: skip
    assert created.status_code == 201, created.text
    token = token_of(created.json()["accept_url"])
    anon = TestClient(app, headers=CLIENT)
    preview = anon.get(f"/auth/invites/{token}")
    assert preview.status_code == 200 and preview.json()["email"] == email
    accepted = anon.post("/auth/invites/accept", json={"token": token, "password": GOOD})
    assert accepted.status_code == 201, accepted.text
    # The link works once.
    assert anon.get(f"/auth/invites/{token}").status_code == 404
    return email, created.json()


def test_non_admin_cannot_use_admin_endpoints(users: dict) -> None:
    assistant = signed_in("assistant@demo.medynium")
    assert assistant.get("/admin/users").status_code == 403
    second_doctor = signed_in("second.doctor@demo.medynium")
    assert second_doctor.get("/admin/users").status_code == 403
    assert TestClient(app).get("/admin/users").status_code == 401


def test_invite_accept_login_and_scoped_access(admin: TestClient, users: dict) -> None:
    email, _ = invite_and_accept(admin, users, ["P-1042", "P-1067"])
    login_limiter.reset()
    user = TestClient(app, headers=CLIENT)
    assert user.post("/auth/login", json={"email": email, "password": GOOD}).status_code == 200
    assert user.get("/me").json()["patient_count"] == 2
    page = user.get("/patients").json()
    assert {i["patient_id"] for i in page["items"]} == {"P-1042", "P-1067"}
    assert user.get(f"/patients/{S3}").status_code == 404
    assert user.get("/admin/users").status_code == 403


def test_assistant_cannot_get_patients_the_supervisor_lacks(admin: TestClient, users: dict) -> None:
    second_doctor_patient = "P-2002"  # entitled to the second doctor, not to Sharma
    bad = admin.post(
        "/admin/invites",
        json={"email": f"x.{secrets.token_hex(3)}@demo.medynium", "display_name": "X", "role": "ASSISTANT",
              "supervising_doctor_id": users["sharma"]["user_id"], "patient_ids": [second_doctor_patient]},
    )  # fmt: skip
    assert bad.status_code == 422


def test_weak_password_is_rejected_at_acceptance(admin: TestClient, users: dict) -> None:
    email = f"test.{secrets.token_hex(4)}@demo.medynium"
    created = admin.post(
        "/admin/invites",
        json={"email": email, "display_name": "T", "role": "ASSISTANT", "supervising_doctor_id": users["sharma"]["user_id"]},
    )  # fmt: skip
    token = token_of(created.json()["accept_url"])
    response = TestClient(app, headers=CLIENT).post(
        "/auth/invites/accept", json={"token": token, "password": "short"}
    )
    assert response.status_code == 422 and response.json()["details"]


def test_lockout_then_disable_and_reset(admin: TestClient, users: dict) -> None:
    email, _ = invite_and_accept(admin, users, ["P-1042"])
    user_id = next(
        u["user_id"] for u in admin.get("/admin/users", params={"q": email}).json()["items"]
    )
    client = TestClient(app, headers=CLIENT)

    for _ in range(5):
        login_limiter.reset()
        assert (
            client.post(
                "/auth/login", json={"email": email, "password": "wrong-password-1"}
            ).status_code
            == 401
        )
    login_limiter.reset()
    # Locked: even the right password is refused, with the same message.
    locked = client.post("/auth/login", json={"email": email, "password": GOOD})
    assert (
        locked.status_code == 401 and locked.json()["message"] == "Email or password is incorrect."
    )

    # Admin reset: a link that sets a new password and lifts the lock.
    reset = admin.post(f"/admin/users/{user_id}/reset-password")
    assert reset.status_code == 201
    token = token_of(reset.json()["accept_url"])
    assert client.get(f"/auth/invites/{token}").json()["kind"] == "PASSWORD_RESET"
    new_password = "another-strong-pass-7"
    assert (
        client.post(
            "/auth/invites/accept", json={"token": token, "password": new_password}
        ).status_code
        == 201
    )
    login_limiter.reset()
    assert (
        client.post("/auth/login", json={"email": email, "password": new_password}).status_code
        == 200
    )

    # Disable: sessions end and sign-in stops; refresh also fails.
    assert (
        admin.patch(f"/admin/users/{user_id}", json={"status": "DISABLED"}).json()["status"]
        == "DISABLED"
    )
    assert client.post("/auth/refresh").status_code == 401
    login_limiter.reset()
    assert (
        client.post("/auth/login", json={"email": email, "password": new_password}).status_code
        == 401
    )

    # Re-enable and entitlements are empty again (a disable revokes them).
    assert (
        admin.patch(f"/admin/users/{user_id}", json={"status": "ACTIVE"}).json()["status"]
        == "ACTIVE"
    )
    assert admin.get(f"/admin/users/{user_id}/entitlements").json()["total"] == 0
    assert admin.put(
        f"/admin/users/{user_id}/entitlements", json={"patient_ids": ["P-1067"]}
    ).json()["patient_ids"] == ["P-1067"]
    admin.patch(f"/admin/users/{user_id}", json={"status": "DISABLED"})


def test_the_last_admin_cannot_be_disabled(admin: TestClient, users: dict) -> None:
    response = admin.patch(
        f"/admin/users/{users['sharma']['user_id']}", json={"status": "DISABLED"}
    )
    assert response.status_code == 409
