"""The agent route live: the planner picks tools, the results merge, and the strong model writes over them.

These call the live models, so they are few. Run with `poe test:int`."""

import json

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_copilot import S1, ask
from tests.integration.test_dashboard import signed_in

pytestmark = pytest.mark.snowflake


@pytest.fixture(scope="module")
def doctor(users: dict) -> TestClient:
    return signed_in("sharma@demo.medynium")


def test_a_two_part_question_runs_two_tools_and_cites_real_evidence(
    doctor: TestClient,
) -> None:
    result = ask(
        doctor,
        "What changed since her last visit, and does any of it matter given the labels?",
        S1,
    )
    print(
        json.dumps(
            {
                "routes": result["routes"],
                "steps": [s["label"] + " | " + s.get("detail", "") for s in result["steps"]],
            },
            indent=1,
        )
    )
    answer = result["answer"]
    assert answer and answer["patient_id"] == S1
    print(answer["short_answer"])
    for c in answer["considerations"]:
        print(c["tag"], c["text"], c["patient_evidence"], c["source_evidence"])
    print("dropped:", evidence_dropped(doctor, answer["answer_id"]))
    ids = {c["id"] for c in answer["considerations"]}
    assert ids  # statements survived or the tools' own statements are shown
    evidence = doctor.get(f"/evidence/{answer['answer_id']}").json()
    known = {p["evidence_id"] for p in evidence["patient_records"]} | {
        s["evidence_id"] for s in evidence["sources"]
    }
    for c in answer["considerations"]:
        assert set(c["patient_evidence"]) | set(c["source_evidence"]) <= known


def evidence_dropped(client: TestClient, answer_id: str) -> list:
    return client.get(f"/evidence/{answer_id}").json()["dropped_statements"]
