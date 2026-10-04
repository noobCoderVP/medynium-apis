"""The brief, attention, changes and gaps endpoints live, and the assistant tools that share their rules."""

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_copilot import S1, S3, ask
from tests.integration.test_dashboard import signed_in

pytestmark = pytest.mark.snowflake
NOT_FOUND = {"error": "not_found", "message": "The requested resource was not found."}


@pytest.fixture(scope="module")
def doctor(users: dict) -> TestClient:
    return signed_in("sharma@demo.medynium")


def test_the_brief_for_the_hero_patient_matches_the_record(doctor: TestClient) -> None:
    body = doctor.get(f"/patients/{S1}/brief").json()
    assert body["patient_id"] == S1 and body["as_of"] == "2026-10-02"
    titles = [i["title"] for i in body["attention"]["items"]]
    assert any(t.startswith("Emergency visit on 2 Oct 2026") for t in titles)
    egfr = next(i for i in body["attention"]["items"] if i["title"].startswith("eGFR 42"))
    assert (
        egfr["severity"] == "high"
        and egfr["source"]["type"] == "lab"
        and egfr["source"]["query"] == {"lab": "eGFR"}
    )
    assert egfr["detail"].startswith("Down from 47")
    assert body["attention"]["counts"]["high"] >= 2
    assert body["changes"]["counts"].get("LAB", 0) >= 1 and body["changes"]["since"] == "2026-08-14"
    assert body["headline"].startswith("58-year-old man")
    assert {r["name"] for r in body["latest_results"]} >= {"eGFR", "HbA1c"}


def test_every_attention_and_change_item_names_a_source(doctor: TestClient) -> None:
    body = doctor.get(f"/patients/{S1}/brief").json()
    for item in [*body["attention"]["items"], *body["changes"]["items"]]:
        assert item["source"]["type"] and item["source"]["tab"], item


def test_changes_take_a_window_and_refuse_nonsense(doctor: TestClient) -> None:
    year = doctor.get(f"/patients/{S1}/changes", params={"from": "1y"}).json()
    short = doctor.get(f"/patients/{S1}/changes", params={"from": "previous_visit"}).json()
    assert len(year["items"]) > len(short["items"])
    assert doctor.get(f"/patients/{S1}/changes", params={"from": "last week"}).status_code == 422


def test_gaps_are_prompts_not_reassurance(doctor: TestClient) -> None:
    items = doctor.get(f"/patients/{S1}/gaps").json()["items"]
    assert any("LDL" in g["title"] for g in items)
    assert all("no risk" not in (g["detail"] or "").lower() for g in items)


def test_a_denied_patient_looks_like_a_missing_one_on_every_route(users: dict) -> None:
    assistant = signed_in("assistant@demo.medynium")
    for path in ("brief", "brief/summary", "attention", "changes", "gaps"):
        denied = assistant.get(f"/patients/{S3}/{path}")
        missing = assistant.get(f"/patients/P-0000/{path}")
        assert denied.status_code == missing.status_code == 404, path
        assert denied.json() == missing.json() == NOT_FOUND, path


def test_the_written_summary_only_restates_the_signals(doctor: TestClient) -> None:
    body = doctor.get(f"/patients/{S1}/brief/summary").json()
    assert body["source"] in ("model", "rules") and len(body["summary"]) > 30
    assert "no risk" not in body["summary"].lower()


def test_the_assistant_answers_attention_and_gaps_from_the_same_rules(doctor: TestClient) -> None:
    result = ask(doctor, "What needs my attention for this patient and what is missing?", S1)
    answer = result["answer"]
    assert answer and answer["patient_id"] == S1
    evidence = doctor.get(f"/evidence/{answer['answer_id']}").json()
    assert any(r["table"] == "CLINICAL.LAB_RESULT" for r in evidence["patient_records"])
    cited = {
        e for c in answer["considerations"] for e in [*c["patient_evidence"], *c["source_evidence"]]
    }
    assert cited <= {r["evidence_id"] for r in evidence["patient_records"]} | {s["evidence_id"] for s in evidence["sources"]}  # fmt: skip


def test_the_assistant_activity_summary_counts_own_entries(doctor: TestClient) -> None:
    ask(doctor, "What are the current medications?", S1)
    body = doctor.get("/audit/summary", params={"days": 7}).json()
    assert body["days"] == 7 and body["asks"] >= 1 and body["entries"] >= body["asks"]
    assert body["median_seconds"] is not None and sum(body["by_route"].values()) == body["asks"]
    assert doctor.get("/audit/summary", params={"days": 0}).status_code == 422


def test_the_written_summary_is_stored_with_its_time_and_can_be_refreshed(
    doctor: TestClient,
) -> None:
    written = doctor.post(f"/patients/{S1}/summary/refresh")
    assert written.status_code == 200, written.text
    body = written.json()
    assert body["exists"] and body["source"] in ("model", "rules") and body["generated_by"]
    md = body["markdown"]
    assert md.startswith("## Snapshot") and "## Medicines" in md and "## Recent results" in md
    assert "42" in md  # the eGFR of the hero patient, copied from the record
    stored = doctor.get(f"/patients/{S1}/summary").json()
    assert (
        stored["markdown"] == md and stored["generated_at"] == body["generated_at"]
    )  # stored, not rewritten on read
    assert stored["changed_since"] is False


def test_a_denied_patients_summary_looks_like_a_missing_one(users: dict) -> None:
    assistant = signed_in("assistant@demo.medynium")
    for method, path in (("get", "summary"), ("post", "summary/refresh")):
        denied = getattr(assistant, method)(f"/patients/{S3}/{path}")
        missing = getattr(assistant, method)(f"/patients/P-0000/{path}")
        assert (
            denied.status_code == missing.status_code == 404
            and denied.json() == missing.json() == NOT_FOUND
        )


def test_records_carry_a_doctor_and_say_how_we_know(doctor: TestClient) -> None:
    timeline = doctor.get(f"/patients/{S1}/timeline", params={"limit": 50}).json()["items"]
    note = next(e for e in timeline if e["type"] == "NOTE")
    assert note["doctor"]["name"] == "Dr. Sharma" and note["doctor"]["basis"] == "author"
    medicines = doctor.get(f"/patients/{S1}/medications").json()["items"]
    assert medicines and all(m["doctor"] and m["doctor"]["name"] == "Dr. Sharma" for m in medicines)
    assert all(m["doctor"]["basis"] in ("treating", "provider", "entered_by") for m in medicines)
    assert doctor.get(f"/patients/{S1}").json()["treating_doctors"] == ["Dr. Sharma"]
