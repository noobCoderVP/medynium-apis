"""Pins, saved views, audit and health with a synthetic stored answer (B-6, B-7)."""

import pytest

from medynium_api.core.ids import new_id
from medynium_api.core.snowflake.role_session import user_cursor
from tests.integration.test_dashboard import signed_in

pytestmark = pytest.mark.snowflake
S1 = "P-1042"


@pytest.fixture
def answer(users: dict) -> str:
    """A stored answer with one patient-record evidence item, inserted as Dr. Sharma."""
    role, uid, answer_id = (
        users["sharma"]["snowflake_role"],
        users["sharma"]["user_id"],
        new_id("ANS", 8),
    )
    with user_cursor(role) as cur:
        cur.execute(
            "INSERT INTO ANALYTICS.ANSWER (ANSWER_ID, PATIENT_ID, USER_ID, KIND, QUESTION, ANSWER_JSON, CREATED_AT) "
            "SELECT %s, %s, %s, 'MEDS', 'test', PARSE_JSON('{}'), SYSDATE()",
            (answer_id, S1, uid),
        )
        cur.execute(
            "INSERT INTO ANALYTICS.ANSWER_EVIDENCE (ANSWER_ID, EVIDENCE_ID, USER_ID, PATIENT_ID, EVIDENCE_KIND, RECORD_TYPE, "
            "RECORD_ID, VALUE_TEXT) SELECT %s, 'P1', %s, %s, 'PATIENT_RECORD', 'LAB_RESULT', 'LAB-77120', 'eGFR 42'",
            (answer_id, uid, S1),
        )
    return answer_id


def test_pin_lifecycle_and_idempotency(users: dict, answer: str) -> None:
    client = signed_in("sharma@demo.medynium")
    body = {"answer_id": answer, "evidence_id": "P1", "note": "check next visit"}
    key = {"Idempotency-Key": new_id("K", 8)}
    first = client.post(f"/patients/{S1}/pins", json=body, headers=key)
    assert first.status_code == 201 and first.json()["label"] == "eGFR 42"
    again = client.post(f"/patients/{S1}/pins", json=body, headers=key)
    assert again.json()["pin_id"] == first.json()["pin_id"]

    def mine() -> list[
        str
    ]:  # other tests also pin on S1, so look only at pins on this test's own answer
        items = client.get(f"/patients/{S1}/pins").json()["items"]
        return [p["pin_id"] for p in items if p["answer_id"] == answer]

    assert mine() == [first.json()["pin_id"]]
    assert client.delete(f"/patients/{S1}/pins/{first.json()['pin_id']}").status_code == 204
    assert mine() == []


def test_pin_on_someone_elses_answer_or_patient_is_not_found(users: dict, answer: str) -> None:
    second = signed_in("second.doctor@demo.medynium")
    assert (
        second.post(
            f"/patients/{S1}/pins", json={"answer_id": answer, "evidence_id": "P1"}
        ).status_code
        == 404
    )
    sharma = signed_in("sharma@demo.medynium")
    assert (
        sharma.post(
            f"/patients/{S1}/pins", json={"answer_id": "ANS-NOPE", "evidence_id": "P1"}
        ).status_code
        == 404
    )


def test_audit_shows_only_own_entries_and_includes_pins(users: dict, answer: str) -> None:
    sharma = signed_in("sharma@demo.medynium")
    pin = sharma.post(f"/patients/{S1}/pins", json={"answer_id": answer, "evidence_id": "P1"})
    sharma.delete(f"/patients/{S1}/pins/{pin.json()['pin_id']}")
    entries = sharma.get("/audit", params={"action": "PIN_EVIDENCE"}).json()
    assert entries["total"] >= 1 and all(e["action"] == "PIN_EVIDENCE" for e in entries["items"])
    other = (
        signed_in("second.doctor@demo.medynium")
        .get("/audit", params={"action": "PIN_EVIDENCE"})
        .json()
    )
    assert other["total"] == 0


def test_saved_view_needs_an_approved_preview(users: dict) -> None:
    client = signed_in("sharma@demo.medynium")
    preview = client.post(
        "/views/preview",
        json={"kind": "VISIT_BRIEF", "patient_id": S1, "content": {"title": "Visit brief"}},
    )
    assert preview.status_code == 200
    pid = preview.json()["preview_id"]
    refused = client.post("/views", json={"preview_id": pid, "approved": False})
    assert refused.status_code == 422
    saved = client.post("/views", json={"preview_id": pid, "approved": True})
    assert saved.status_code == 201 and saved.json()["title"] == "Visit brief"
    assert (
        client.post("/views", json={"preview_id": pid, "approved": True}).status_code == 404
    )  # single use
    assert any(
        v["view_id"] == saved.json()["view_id"]
        for v in client.get("/views", params={"patient_id": S1}).json()
    )
    assert (
        signed_in("assistant@demo.medynium")
        .post("/views/preview", json={"kind": "SAVED_VIEW", "patient_id": "P-1093", "content": {}})
        .status_code
        == 404
    )


def test_health_details_are_admin_only(users: dict) -> None:
    details = signed_in("sharma@demo.medynium").get("/health/details")
    assert details.status_code == 200
    body = details.json()
    assert body["snowflake"]["reachable"] is True and body["snowflake"]["service_role"] == "MED_API"
    assert body["audit_writes"] == "ok" and "account" not in str(body).lower()
    assert signed_in("assistant@demo.medynium").get("/health/details").status_code == 403
