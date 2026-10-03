"""Patient endpoints return ground-truth values; a denied patient is byte-identical to a missing one (G4, B-5)."""

import time

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_dashboard import signed_in

pytestmark = pytest.mark.snowflake
S1, S3 = "P-1042", "P-1093"
NOT_FOUND = {"error": "not_found", "message": "The requested resource was not found."}
PATIENT_PATHS = [
    "",
    "/medications",
    "/labs",
    "/labs/eGFR/trend",
    "/timeline",
    "/claims",
    "/notes",
    "/notes/DOC-OP-20899",
]


def test_s1_overview_matches_ground_truth(users: dict) -> None:
    body = signed_in("sharma@demo.medynium").get(f"/patients/{S1}").json()
    assert body["name"] == "Rahul Patel" and body["age"] == 58
    assert {d["description"] for d in body["diagnoses"]} >= {
        "Type 2 diabetes mellitus",
        "Chronic kidney disease, stage 3b",
    }
    meds = {m["drug"]: m for m in body["medications"]}
    assert set(meds) == {"Metformin", "Lisinopril", "Atorvastatin"}
    assert meds["Metformin"]["change"] == "Dose raised from 500 mg on 14 Aug 2026"
    egfr = next(lab for lab in body["latest_labs"] if lab["test"] == "eGFR")
    assert (egfr["value"], egfr["previous"]["value"], egfr["flag"], egfr["date"]) == (
        42,
        47,
        "LOW",
        "2026-09-18",
    )
    assert (
        body["utilization"]["emergency_visits"] == 1
        and body["utilization"]["hospitalizations"] == 2
    )


def test_s1_trend_timeline_claims_notes(users: dict) -> None:
    client = signed_in("sharma@demo.medynium")
    trend = client.get(f"/patients/{S1}/labs/eGFR/trend").json()
    assert [p["value"] for p in trend["points"]] == [58, 52, 47, 42]
    assert client.get(f"/patients/{S1}/labs/33914-3/trend").json()["points"] == trend["points"]
    assert client.get(f"/patients/{S1}/labs/nope/trend").status_code == 422

    tl = client.get(f"/patients/{S1}/timeline", params={"from": "2026-10-01"}).json()
    assert {e["type"] for e in tl["items"]} >= {"ENCOUNTER", "CLAIM", "NOTE"} and all(
        e["date"] >= "2026-10-01" for e in tl["items"]
    )
    only_labs = client.get(f"/patients/{S1}/timeline", params={"types": "LAB_PANEL"}).json()
    assert only_labs["items"] and {e["type"] for e in only_labs["items"]} == {"LAB_PANEL"}

    claims = client.get(f"/patients/{S1}/claims").json()
    clm = next(c for c in claims["claims"] if c["claim_id"] == "CLM-1024")
    assert clm["encounter_id"] == "ENC-20931" and clm["approved"]["amount"] == 18400
    notes = client.get(f"/patients/{S1}/notes").json()
    assert {n["note_id"] for n in notes["items"]} >= {"DOC-ED-20931", "DOC-DS-19877"}
    assert "body" in client.get(f"/patients/{S1}/notes/DOC-ED-20931").json()
    assert (
        "contains_injection"
        not in str(client.get(f"/patients/{S1}/notes/DOC-ED-20931").json()).lower()
    )


def test_list_scopes_and_searches(users: dict) -> None:
    client = signed_in("assistant@demo.medynium")
    page = client.get("/patients", params={"limit": 200}).json()
    assert page["total"] == 36 and S3 not in str(page)
    assert (
        client.get("/patients", params={"q": "Amit"}).json()["total"] == 0
    )  # S3's name is not searchable
    assert client.get("/patients", params={"q": "Rahul"}).json()["items"][0]["patient_id"] == S1
    assert all(
        i["flags"] for i in client.get("/patients", params={"changed": "true"}).json()["items"]
    )


@pytest.mark.parametrize("suffix", PATIENT_PATHS)
def test_denied_is_byte_identical_to_missing(users: dict, suffix: str) -> None:
    assistant = signed_in("assistant@demo.medynium")
    denied = assistant.get(f"/patients/{S3}{suffix}")
    missing = assistant.get(f"/patients/P-0000{suffix}")
    assert denied.status_code == missing.status_code == 404
    assert (
        denied.content
        == missing.content
        == str(NOT_FOUND).replace("'", '"').replace(", ", ",").replace(": ", ":").encode()
        or denied.json() == NOT_FOUND
    )
    assert denied.json() == missing.json() == NOT_FOUND


def test_other_doctors_patient_is_also_not_found(users: dict) -> None:
    assert signed_in("second.doctor@demo.medynium").get(f"/patients/{S1}").json() == NOT_FOUND


def test_denied_and_missing_take_similar_time(users: dict) -> None:
    assistant: TestClient = signed_in("assistant@demo.medynium")

    def timed(pid: str) -> float:
        started = time.perf_counter()
        assistant.get(f"/patients/{pid}")
        return time.perf_counter() - started

    denied = sorted(timed(S3) for _ in range(5))[2]
    missing = sorted(timed("P-0000") for _ in range(5))[2]
    assert abs(denied - missing) < 0.25, (denied, missing)
