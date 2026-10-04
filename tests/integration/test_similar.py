"""Similar-patient search against the live account (production plan Phase 5, gate G6): every match explains itself from
real records, only the caller's own patients can appear, and nothing identifying is ever embedded."""

import secrets
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from medynium_api.core.security.ratelimit import ask_limiter
from tests.integration.purge import connect, purge_test_patients
from tests.integration.test_dashboard import signed_in

pytestmark = pytest.mark.snowflake
S1, S2, S3 = "P-1042", "P-1067", "P-1093"
NOT_FOUND = {"error": "not_found", "message": "The requested resource was not found."}
JSON = {"Accept": "application/json"}


@pytest.fixture(scope="module", autouse=True)
def clean_up() -> Iterator[None]:
    purge_test_patients()
    yield
    purge_test_patients()


@pytest.fixture(scope="module")
def doctor(users: dict) -> TestClient:
    return signed_in("sharma@demo.medynium")


@pytest.fixture(scope="module")
def assistant(users: dict) -> TestClient:
    return signed_in("assistant@demo.medynium")


def own_ids(client: TestClient) -> set[str]:
    return {p["patient_id"] for p in client.get("/patients", params={"limit": 200}).json()["items"]}


def test_the_kidney_patients_closest_cases_are_kidney_and_diabetes_patients(
    doctor: TestClient,
) -> None:
    body = doctor.get(f"/patients/{S1}/similar", params={"limit": 5}).json()
    items = body["items"]
    assert (
        body["ready"] and len(items) == 5 and body["requested"] == 5 and body["scoring"] == "blend"
    )
    assert S1 not in {i["patient_id"] for i in items}
    scores = [i["score"] for i in items]
    assert scores == sorted(scores, reverse=True) and all(0 < s <= 1 for s in scores)
    for i in items:
        assert (
            i["why"]
            and i["name"]
            and set(i["parts"]) == {"embedding", "diagnoses", "medicines", "labs", "age"}
        )
        assert any(
            "kidney" in d.lower() or "diabetes" in d.lower() for d in i["shared_diagnoses"]
        ), i
    assert "Not a prediction" in body["disclaimer"]


def test_only_the_callers_own_patients_can_appear(
    doctor: TestClient, assistant: TestClient
) -> None:
    mine = own_ids(doctor)
    assert {
        i["patient_id"]
        for i in doctor.get(f"/patients/{S1}/similar", params={"limit": 10}).json()["items"]
    } <= mine
    theirs = own_ids(assistant)
    seen = assistant.get(f"/patients/{S1}/similar", params={"limit": 10}).json()["items"]
    assert {i["patient_id"] for i in seen} <= theirs and S3 not in {i["patient_id"] for i in seen}


def test_a_denied_patient_is_the_same_404_as_a_missing_one(assistant: TestClient) -> None:
    denied = assistant.get(f"/patients/{S3}/similar")
    missing = assistant.get("/patients/P-0000/similar")
    assert (
        (denied.status_code, denied.json())
        == (404, NOT_FOUND)
        == (missing.status_code, missing.json())
    )


def test_the_list_is_never_padded(doctor: TestClient) -> None:
    body = doctor.get(f"/patients/{S2}/similar", params={"limit": 10}).json()
    assert len(body["items"]) <= 10
    if len(body["items"]) < 10:
        assert "not padded" in body["note"]
    assert all(i["score"] >= 0.30 for i in body["items"])


def test_the_search_is_audited_and_needs_a_session(
    doctor: TestClient, assistant: TestClient
) -> None:
    doctor.get(f"/patients/{S1}/similar")
    assistant.get(f"/patients/{S3}/similar")
    mine = {
        (a["action"], a["outcome"])
        for a in doctor.get("/audit", params={"limit": 50}).json()["items"]
    }
    assert ("SIMILAR_PATIENTS", "OK") in mine
    theirs = {
        (a["action"], a["outcome"])
        for a in assistant.get("/audit", params={"limit": 50}).json()["items"]
    }
    assert ("SIMILAR_PATIENTS", "DENIED") in theirs
    anon = TestClient(doctor.app, headers={"X-Medynium-Client": "web"})
    assert anon.get(f"/patients/{S1}/similar").status_code == 401


def test_nothing_that_identifies_a_person_is_embedded(users: dict) -> None:
    conn = connect("MED_ADMIN", "MEDYNIUM")
    try:
        cur = conn.cursor()
        cur.execute("USE WAREHOUSE MEDYNIUM_WH")
        cur.execute(
            "SELECT COUNT(*) FROM ANALYTICS.PATIENT_EMBEDDING e JOIN CLINICAL.PATIENT p ON p.PATIENT_ID = e.PATIENT_ID "
            "WHERE CONTAINS(LOWER(e.SUMMARY_TEXT), LOWER(p.FULL_NAME)) OR CONTAINS(e.SUMMARY_TEXT, p.PATIENT_ID) "
            "OR (p.CITY IS NOT NULL AND CONTAINS(LOWER(e.SUMMARY_TEXT), LOWER(p.CITY)))"
        )
        assert cur.fetchone()[0] == 0
        cur.execute(  # S5's note carries an instruction aimed at AI tools; note text must never reach a summary
            "SELECT COUNT(*) FROM ANALYTICS.PATIENT_EMBEDDING WHERE PATIENT_ID = 'P-1118' "
            "AND (CONTAINS(LOWER(SUMMARY_TEXT), 'ignore') OR CONTAINS(LOWER(SUMMARY_TEXT), 'instruction'))"
        )
        assert cur.fetchone()[0] == 0
    finally:
        conn.close()


def test_a_new_patient_gets_a_vector_after_a_change_and_an_unchanged_one_is_not_re_embedded(
    doctor: TestClient,
) -> None:
    created = doctor.post(
        "/patients",
        json={
            "full_name": f"Zz Test {secrets.token_hex(3)}",
            "birth_date": "1966-04-04",
            "sex": "M",
        },
    ).json()
    pid = created["patient_id"]
    doctor.post(
        f"/patients/{pid}/diagnoses",
        json={"description": "Type 2 diabetes mellitus", "onset_date": "2020-01-10"},
    )
    doctor.post(f"/patients/{pid}/medications", json={"description": "Metformin", "dose_text": "500 mg twice daily", "start_date": "2024-01-01"})  # fmt: skip
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline and doctor.get(f"/patients/{pid}/sync").json()["pending"]:
        time.sleep(1)
    body = doctor.get(f"/patients/{pid}/similar", params={"limit": 3}).json()
    assert body["ready"] is True and body["items"], body
    assert any("diabetes" in d.lower() for i in body["items"] for d in i["shared_diagnoses"])
    conn = connect("MED_ADMIN", "MEDYNIUM")
    try:
        cur = conn.cursor()
        cur.execute("USE WAREHOUSE MEDYNIUM_WH")
        cur.execute(
            "SELECT BUILT_AT FROM ANALYTICS.PATIENT_EMBEDDING WHERE PATIENT_ID = %s", (pid,)
        )
        built = cur.fetchone()[0]
        cur.execute("CALL INTAKE.REFRESH_EMBEDDING(%s)", (pid,))
        assert cur.fetchone()[0] == "unchanged"
        cur.execute(
            "SELECT BUILT_AT FROM ANALYTICS.PATIENT_EMBEDDING WHERE PATIENT_ID = %s", (pid,)
        )
        assert cur.fetchone()[0] == built  # no second embedding call for an unchanged summary
    finally:
        conn.close()


def test_the_assistant_answers_have_i_seen_a_case_like_this(doctor: TestClient) -> None:
    ask_limiter.reset()
    response = doctor.post(
        "/copilot/ask",
        json={
            "question": "have I seen a case like this before?",
            "screen": "patient",
            "patient_id": S1,
        },
        headers=JSON,
    )
    assert response.status_code == 200, response.text
    answer = response.json()["answer"]
    assert answer["kind"] == "PANEL" and answer["considerations"]
    assert {c["group"] for c in answer["considerations"]} == {"Similar patients"}
    assert all(
        "match" in c["text"] and c["patient_id"] in own_ids(doctor)
        for c in answer["considerations"]
    )
    assert any("Not a prediction" in n for n in answer["limits"]["notes"])
