"""The write path against the live account (production plan Phase 1, gate G2).

Every test registers its own "Zz Test" patient and the module removes them afterwards, so the seeded demo data is never
touched. The read models are pinned to 2026-10-02 (conftest), so records are dated on or before that day."""

import secrets
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.integration.purge import purge_test_patients
from tests.integration.test_dashboard import signed_in

pytestmark = pytest.mark.snowflake
S1, S3 = "P-1042", "P-1093"
NOT_FOUND = {"error": "not_found", "message": "The requested resource was not found."}


@pytest.fixture(scope="module", autouse=True)
def clean_up() -> Iterator[None]:
    purge_test_patients()
    yield
    purge_test_patients()


@pytest.fixture(scope="module")
def doctor(users: dict) -> TestClient:
    return signed_in("sharma@demo.medynium")


def settle(client: TestClient, pid: str, seconds: float = 90) -> None:
    """Wait for the background refresh that follows a write, as the screens do (they poll /sync)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not client.get(f"/patients/{pid}/sync").json()["pending"]:
            return
        time.sleep(1)
    raise AssertionError(f"read models for {pid} were still updating after {seconds} s")


def new_patient(client: TestClient, **over: object) -> dict:
    body = {
        "full_name": f"Zz Test {secrets.token_hex(3)}", "birth_date": "1975-03-04", "sex": "F",
        "city": "Pune", "state": "Maharashtra", "pin_code": "411001", "phone": "+91 98765 43210", **over,
    }  # fmt: skip
    response = client.post(
        "/patients", json=body, headers={"Idempotency-Key": f"test-{secrets.token_hex(6)}"}
    )
    assert response.status_code == 201, response.text
    return {**response.json(), "name": body["full_name"]}


@pytest.fixture
def patient(doctor: TestClient) -> dict:
    return new_patient(doctor)


def test_a_new_patient_is_on_the_list_and_open_straight_away(
    doctor: TestClient, patient: dict
) -> None:
    pid = patient["patient_id"]
    assert patient["version"] == 1 and pid.startswith("P-")
    listed = doctor.get("/patients", params={"q": patient["name"]}).json()
    assert [p["patient_id"] for p in listed["items"]] == [pid]
    overview = doctor.get(f"/patients/{pid}")
    assert overview.status_code == 200 and overview.json()["name"] == patient["name"]


def test_every_kind_of_record_can_be_added_and_shows_up(doctor: TestClient, patient: dict) -> None:
    pid = patient["patient_id"]
    d = doctor.post(
        f"/patients/{pid}/diagnoses",
        json={"description": "Type 2 diabetes mellitus", "onset_date": "2020-01-10"},
    )
    m = doctor.post(
        f"/patients/{pid}/medications",
        json={
            "description": "Glycomet 500",
            "dose_text": "500 mg twice daily",
            "start_date": "2024-01-01",
        },
    )
    lab = doctor.post(
        f"/patients/{pid}/labs",
        json={"loinc_code": "33914-3", "value_num": 41, "observed_at": "2026-09-30T10:00:00"},
    )
    a = doctor.post(
        f"/patients/{pid}/allergies",
        json={"substance": "Penicillin", "reaction": "Rash", "severity": "MODERATE"},
    )
    n = doctor.post(
        f"/patients/{pid}/notes",
        json={"title": "First visit", "body": "Counselled on diet.", "note_date": "2026-09-30"},
    )
    v = doctor.post(f"/patients/{pid}/visits", json={"started_at": "2026-09-30T09:00:00", "visit_kind": "OUTPATIENT", "description": "Clinic visit"})  # fmt: skip
    for response in (d, m, lab, a, n, v):
        assert response.status_code == 201, response.text
        assert response.json()["version"] == 1
    settle(doctor, pid)
    body = doctor.get(f"/patients/{pid}").json()
    assert [x["description"] for x in body["diagnoses"]] == ["Type 2 diabetes mellitus"]
    med = body["medications"][0]
    assert (
        med["drug"] == "Metformin" and med["description"] == "Glycomet 500"
    )  # a brand resolved to its generic
    assert med["in_knowledge_base"] is True
    egfr = next(x for x in body["latest_labs"] if x["test"] == "eGFR")
    assert (
        egfr["value"] == 41 and egfr["flag"] == "LOW" and egfr["unit"]
    )  # unit and flag come from the reference table
    assert [x["substance"] for x in body["allergies"]] == ["Penicillin"]
    types = {
        e["type"]
        for e in doctor.get(f"/patients/{pid}/timeline", params={"limit": 100}).json()["items"]
    }
    assert {"ENCOUNTER", "DIAGNOSIS", "MEDICATION_START", "LAB_PANEL", "NOTE"} <= types


def test_a_dose_change_is_a_medication_change_and_a_stale_edit_is_refused(
    doctor: TestClient, patient: dict
) -> None:
    pid = patient["patient_id"]
    made = doctor.post(f"/patients/{pid}/medications", json={"description": "Metformin", "dose_text": "500 mg twice daily", "start_date": "2026-01-01"}).json()  # fmt: skip
    edit = {
        "description": "Metformin",
        "dose_text": "1000 mg twice daily",
        "start_date": "2026-01-01",
        "version": made["version"],
    }
    done = doctor.put(f"/patients/{pid}/medications/{made['record_id']}", json=edit)
    assert done.status_code == 200 and done.json()["version"] == 2
    settle(doctor, pid)
    med = doctor.get(f"/patients/{pid}").json()["medications"][0]
    assert med["dose"] == "1000 mg twice daily" and "500 mg" in med["change"]
    stale = doctor.put(
        f"/patients/{pid}/medications/{made['record_id']}", json=edit
    )  # still says version 1
    assert stale.status_code == 409 and stale.json()["error"] == "conflict"
    row = doctor.get(f"/patients/{pid}/records/medications/{made['record_id']}").json()
    assert row["version"] == 2 and row["fields"]["dose_text"] == "1000 mg twice daily"


def test_archiving_hides_a_record_everywhere_and_restore_brings_it_back(
    doctor: TestClient, patient: dict
) -> None:
    pid = patient["patient_id"]
    lab = doctor.post(f"/patients/{pid}/labs", json={"loinc_code": "4548-4", "value_num": 8.1, "observed_at": "2026-09-29T08:00:00"}).json()  # fmt: skip
    settle(doctor, pid)
    assert any(x["test"] == "HbA1c" for x in doctor.get(f"/patients/{pid}").json()["latest_labs"])
    gone = doctor.post(
        f"/patients/{pid}/labs/{lab['record_id']}/archive",
        json={"version": 1, "reason": "entered in error"},
    )
    assert gone.status_code == 200 and gone.json()["version"] == 2
    settle(doctor, pid)
    assert not any(
        x["test"] == "HbA1c" for x in doctor.get(f"/patients/{pid}").json()["latest_labs"]
    )
    assert doctor.get(f"/patients/{pid}/records/labs").json()["items"] == []
    listed = doctor.get(f"/patients/{pid}/records/labs", params={"include_archived": True}).json()[
        "items"
    ]
    assert [r["is_archived"] for r in listed] == [True]
    back = doctor.post(f"/patients/{pid}/labs/{lab['record_id']}/restore", json={"version": 2})
    assert back.status_code == 200
    settle(doctor, pid)
    assert any(x["test"] == "HbA1c" for x in doctor.get(f"/patients/{pid}").json()["latest_labs"])
    ops = [
        (h["op"], h["actor_name"])
        for h in doctor.get(f"/patients/{pid}/history").json()["items"]
        if h["entity"] == "LAB_RESULT"
    ]
    assert ops == [("RESTORE", "Dr. Sharma"), ("ARCHIVE", "Dr. Sharma"), ("CREATE", "Dr. Sharma")]
    assert doctor.get(f"/patients/{pid}/history").json()["items"][-1]["op"] == "CREATE"


def test_an_archived_patient_is_missing_everywhere_until_restored(
    doctor: TestClient, patient: dict
) -> None:
    pid = patient["patient_id"]
    assert doctor.post(f"/patients/{pid}/archive", json={"version": 1}).status_code == 200
    assert doctor.get(f"/patients/{pid}").json() == NOT_FOUND
    assert pid not in [
        p["patient_id"]
        for p in doctor.get("/patients", params={"q": patient["name"]}).json()["items"]
    ]
    archived = doctor.get("/archived-patients").json()["items"]
    entry = next(a for a in archived if a["patient_id"] == pid)
    assert (
        doctor.post(f"/patients/{pid}/restore", json={"version": entry["version"]}).status_code
        == 200
    )
    assert doctor.get(f"/patients/{pid}").status_code == 200


def test_editing_demographics_and_the_duplicate_warning(doctor: TestClient, patient: dict) -> None:
    pid = patient["patient_id"]
    body = {
        "full_name": patient["name"],
        "birth_date": "1975-03-04",
        "sex": "F",
        "city": "Nagpur",
        "version": 1,
    }
    assert doctor.put(f"/patients/{pid}", json=body).json()["version"] == 2
    again = {"full_name": patient["name"], "birth_date": "1975-03-04", "sex": "F"}
    refused = doctor.post("/patients", json=again)
    assert refused.status_code == 409 and "already on your list" in refused.json()["message"]
    allowed = doctor.post("/patients", json={**again, "confirm_duplicate": True})
    assert allowed.status_code == 201 and allowed.json()["patient_id"] != pid


def test_the_same_idempotency_key_writes_once(doctor: TestClient, patient: dict) -> None:
    pid = patient["patient_id"]
    key = {"Idempotency-Key": f"test-{secrets.token_hex(6)}"}
    body = {"substance": "Sulfa drugs", "severity": "MILD"}
    first = doctor.post(f"/patients/{pid}/allergies", json=body, headers=key).json()
    second = doctor.post(f"/patients/{pid}/allergies", json=body, headers=key).json()
    assert first == second
    assert len(doctor.get(f"/patients/{pid}/records/allergies").json()["items"]) == 1


def test_bad_input_is_a_field_level_422(doctor: TestClient, patient: dict) -> None:
    pid = patient["patient_id"]
    bad = doctor.post(f"/patients/{pid}/labs", json={"loinc_code": "33914-3", "value_num": -5, "observed_at": "2999-01-01T00:00:00", "is_archived": True})  # fmt: skip
    assert bad.status_code == 422
    fields = {d["field"] for d in bad.json()["details"]}
    assert {"value_num", "observed_at", "is_archived"} <= fields
    unknown = doctor.post(f"/patients/{pid}/labs", json={"loinc_code": "9999-9", "value_num": 1, "observed_at": "2026-09-01T10:00:00"})  # fmt: skip
    assert unknown.status_code == 422 and unknown.json()["error"] == "invalid_request"
    assert "Traceback" not in bad.text and pid not in unknown.text


def test_an_assistant_cannot_write_and_a_stranger_gets_the_same_404_as_a_missing_patient(users: dict, doctor: TestClient, patient: dict) -> None:  # fmt: skip
    pid = patient["patient_id"]
    assistant = signed_in("assistant@demo.medynium")
    assert (
        assistant.post(f"/patients/{S1}/allergies", json={"substance": "Penicillin"}).status_code
        == 403
    )
    assert (
        assistant.post(
            "/patients", json={"full_name": "Zz Test no", "birth_date": "1990-01-01", "sex": "M"}
        ).status_code
        == 403
    )
    other = signed_in("second.doctor@demo.medynium")  # a doctor who does not have this patient
    attempts = [
        ("post", f"/patients/{pid}/allergies", {"substance": "Aspirin"}),
        ("put", f"/patients/{pid}/allergies/ALG-1", {"substance": "Aspirin", "version": 1}),
        ("post", f"/patients/{pid}/allergies/ALG-1/archive", {"version": 1}),
        ("post", f"/patients/{pid}/archive", {"version": 1}),
        ("get", f"/patients/{pid}/records/allergies", None),
        ("get", f"/patients/{pid}/history", None),
    ]
    for verb, path, body in attempts:
        denied = getattr(other, verb)(path, **({"json": body} if body is not None else {}))
        missing_path = path.replace(pid, "P-9999")
        missing = getattr(other, verb)(missing_path, **({"json": body} if body is not None else {}))
        assert (
            (denied.status_code, denied.json())
            == (404, NOT_FOUND)
            == (missing.status_code, missing.json())
        ), path
    assert (
        doctor.get(f"/patients/{pid}/records/allergies").json()["items"] == []
    )  # nothing was written


def test_writes_need_a_session(doctor: TestClient, patient: dict) -> None:
    anon = TestClient(doctor.app, headers={"X-Medynium-Client": "web"})
    assert (
        anon.post(
            "/patients", json={"full_name": "x", "birth_date": "1990-01-01", "sex": "M"}
        ).status_code
        == 401
    )
    assert (
        anon.post(
            f"/patients/{patient['patient_id']}/notes", json={"title": "t", "body": "b"}
        ).status_code
        == 401
    )


def test_writes_are_in_the_activity_log_and_a_denial_is_too(
    users: dict, doctor: TestClient, patient: dict
) -> None:
    pid = patient["patient_id"]
    doctor.post(
        f"/patients/{pid}/notes", json={"title": "Logged", "body": "b", "note_date": "2026-09-30"}
    )
    other = signed_in("second.doctor@demo.medynium")
    other.post(f"/patients/{pid}/notes", json={"title": "Nope", "body": "b"})
    mine = {
        (a["action"], a["outcome"])
        for a in doctor.get("/audit", params={"limit": 50}).json()["items"]
    }
    assert ("WRITE_CLINICAL_NOTE_CREATE", "OK") in mine
    theirs = {
        (a["action"], a["outcome"])
        for a in other.get("/audit", params={"limit": 50}).json()["items"]
    }
    assert ("WRITE_CLINICAL_NOTE_CREATE", "DENIED") in theirs
