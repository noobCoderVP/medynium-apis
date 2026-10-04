"""Write proposals live: the assistant prepares, the doctor approves, nothing is written before that.

Calls the live planner model, so it is deliberate rather than numerous. Run with `poe test:int`."""

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_copilot import S1, ask
from tests.integration.test_dashboard import signed_in

pytestmark = pytest.mark.snowflake
QUESTION = "record a penicillin allergy, rash, moderate"


@pytest.fixture(scope="module")
def doctor(users: dict) -> TestClient:
    return signed_in("sharma@demo.medynium")


def allergies(client: TestClient) -> list[dict]:
    response = client.get(f"/patients/{S1}/records/allergies")
    assert response.status_code == 200, response.text
    return [r for r in response.json()["items"] if not r["is_archived"]]


def test_a_proposal_writes_nothing_until_approved_then_writes_once(doctor: TestClient) -> None:
    before = len(allergies(doctor))
    result = ask(doctor, QUESTION, S1)
    assert len(result["proposals"]) == 1, result
    proposal = result["proposals"][0]
    assert proposal["kind"] == "add_allergy" and proposal["patient_id"] == S1
    assert {"label": "Substance", "value": "penicillin"} in proposal["fields"]
    assert len(allergies(doctor)) == before  # prepared, not saved

    base = f"/agent/proposals/{proposal['proposal_id']}"
    first = doctor.post(f"{base}/approve")
    assert first.status_code == 200, first.text
    again = doctor.post(f"{base}/approve")
    assert again.json() == first.json()  # a second click returns the first result
    after = allergies(doctor)
    assert len(after) == before + 1  # written exactly once

    created = next(r for r in after if r["record_id"] == first.json()["record_id"])
    assert created["fields"]["substance"].lower() == "penicillin"
    cleanup = doctor.post(
        f"/patients/{S1}/allergies/{created['record_id']}/archive",
        json={"version": created["version"], "reason": "test cleanup"},
    )
    assert cleanup.status_code == 200, cleanup.text


def test_a_discarded_or_foreign_proposal_cannot_be_approved(
    doctor: TestClient, users: dict
) -> None:
    proposal = ask(doctor, QUESTION, S1)["proposals"][0]
    base = f"/agent/proposals/{proposal['proposal_id']}"
    assert signed_in("second.doctor@demo.medynium").post(f"{base}/approve").status_code == 404
    assert doctor.post(f"{base}/discard").status_code == 200
    assert doctor.post(f"{base}/approve").status_code == 404


def test_an_assistant_is_told_only_a_doctor_can_add_records(users: dict) -> None:
    result = ask(signed_in("assistant@demo.medynium"), QUESTION, S1)
    assert result["proposals"] == []
    assert result["refusal"] and result["refusal"]["reason"] == "needs_doctor"


def test_editing_deleting_and_bulk_writes_are_still_refused(doctor: TestClient) -> None:
    for question in (
        "change her metformin dose to 500 mg",
        "delete the last note",
        "add a note to all my patients",
    ):
        result = ask(doctor, question, S1)
        assert result["proposals"] == [] and result["refusal"], question


def test_invented_free_text_is_not_carried_into_the_preview(doctor: TestClient) -> None:
    result = ask(doctor, "add a note: patient reports dizziness on standing", S1)
    if result["proposals"]:  # the body can only be words the clinician said
        text = " ".join(f["value"] for f in result["proposals"][0]["fields"]).lower()
        assert "dizziness" in text
        doctor.post(f"/agent/proposals/{result['proposals'][0]['proposal_id']}/discard")
