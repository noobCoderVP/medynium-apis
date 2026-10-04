"""Pending work and the assistant's panel tools against the live account (production plan Phase 3, gate G4).

The question that defines the phase is "who are my patients and what is pending?". It is asked of the assistant
and answered from the same view as the Pending page, under the asker's own role."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from medynium_api.core.security.ratelimit import ask_limiter
from medynium_api.features.copilot import routing
from medynium_api.features.copilot.routing import Step
from tests.integration.purge import clear_lab_reviews
from tests.integration.test_dashboard import signed_in

pytestmark = pytest.mark.snowflake
S1, S3 = "P-1042", "P-1093"
NOT_FOUND = {"error": "not_found", "message": "The requested resource was not found."}
JSON = {"Accept": "application/json"}


@pytest.fixture(scope="module")
def doctor(users: dict) -> TestClient:
    return signed_in("sharma@demo.medynium")


@pytest.fixture(scope="module")
def assistant(users: dict) -> TestClient:
    return signed_in("assistant@demo.medynium")


@pytest.fixture
def reviewed() -> Iterator[list[str]]:
    marks: list[str] = []
    yield marks
    clear_lab_reviews(marks)


def ask(
    client: TestClient, question: str, patient: str | None = None, screen: str = "dashboard"
) -> dict:
    ask_limiter.reset()
    response = client.post(
        "/copilot/ask",
        json={"question": question, "screen": screen, "patient_id": patient},
        headers=JSON,
    )
    assert response.status_code == 200, response.text
    return response.json()


def all_pending(client: TestClient) -> list[dict]:
    return client.get("/pending", params={"limit": 200}).json()["items"]


# The Pending page ------------------------------------------------------------------------------------------------
def test_the_pending_page_lists_what_is_waiting_most_urgent_first(doctor: TestClient) -> None:
    page = doctor.get("/pending", params={"limit": 200}).json()
    assert page["total"] == len(page["items"]) > 0 and page["as_of"] == "2026-10-02"
    mine = [i for i in page["items"] if i["patient_id"] == S1]
    kinds = {i["kind"] for i in mine}
    assert "ABNORMAL_LAB" in kinds and "RECENT_EMERGENCY" in kinds, kinds
    lab = next(i for i in mine if i["kind"] == "ABNORMAL_LAB")
    assert (
        "eGFR" in lab["title"] and lab["source_table"] == "CLINICAL.LAB_RESULT" and lab["source_id"]
    )
    order = [
        "ESCALATED_FINDING",
        "FOLLOW_UP",
        "OPEN_FINDING",
        "REPORT_TO_REVIEW",
        "ABNORMAL_LAB",
        "RECENT_EMERGENCY",
    ]
    ranks = [order.index(i["kind"]) for i in page["items"]]
    assert ranks == sorted(ranks)


def test_the_summary_matches_the_list_and_filters_narrow_it(doctor: TestClient) -> None:
    items = all_pending(doctor)
    summary = doctor.get("/pending/summary").json()
    assert summary["total"] == len(items)
    assert summary["by_kind"] == {
        k: sum(1 for i in items if i["kind"] == k) for k in summary["by_kind"]
    }
    only = doctor.get("/pending", params={"kind": "ABNORMAL_LAB", "limit": 200}).json()["items"]
    assert only and {i["kind"] for i in only} == {"ABNORMAL_LAB"}
    one = doctor.get("/pending", params={"patient_id": S1}).json()["items"]
    assert one and {i["patient_id"] for i in one} == {S1}


def test_a_patient_the_user_does_not_have_never_appears(
    doctor: TestClient, assistant: TestClient
) -> None:
    assert all(i["patient_id"] != S3 for i in all_pending(assistant))
    assistant_ids = {i["patient_id"] for i in all_pending(assistant)}
    doctor_ids = {i["patient_id"] for i in all_pending(doctor)}
    assert (
        assistant_ids <= doctor_ids
    )  # an assistant's pending list is a subset of the supervising doctor's
    denied = assistant.get("/pending", params={"patient_id": S3})
    missing = assistant.get("/pending", params={"patient_id": "P-0000"})
    assert (
        (denied.status_code, denied.json())
        == (404, NOT_FOUND)
        == (missing.status_code, missing.json())
    )


def test_marking_a_lab_reviewed_clears_it_and_only_a_doctor_may(
    doctor: TestClient, assistant: TestClient, reviewed: list[str]
) -> None:
    lab = next(
        i for i in all_pending(doctor) if i["kind"] == "ABNORMAL_LAB" and i["patient_id"] == S1
    )
    lab_id = lab["source_id"]
    assert assistant.post(f"/patients/{S1}/labs/{lab_id}/review").status_code == 403
    assert any(i["source_id"] == lab_id for i in all_pending(doctor))  # the refusal changed nothing
    reviewed.append(lab_id)
    done = doctor.post(f"/patients/{S1}/labs/{lab_id}/review")
    assert done.status_code == 200 and done.json()["lab_id"] == lab_id
    assert (
        doctor.post(f"/patients/{S1}/labs/{lab_id}/review").json()["reviewed_at"]
        == done.json()["reviewed_at"]
    )
    assert not any(i["source_id"] == lab_id for i in all_pending(doctor))


def test_reviewing_a_lab_of_a_patient_you_do_not_have_or_that_is_not_pending_is_a_404(users: dict, doctor: TestClient) -> None:  # fmt: skip
    other = signed_in("second.doctor@demo.medynium")
    lab_id = next(i for i in all_pending(doctor) if i["kind"] == "ABNORMAL_LAB")["source_id"]
    stranger = other.post(f"/patients/{S1}/labs/{lab_id}/review")
    assert (stranger.status_code, stranger.json()) == (404, NOT_FOUND)
    assert doctor.post(f"/patients/{S1}/labs/LAB-NOT-REAL/review").status_code == 404


# The assistant ---------------------------------------------------------------------------------------------------
def test_who_are_my_patients_and_what_is_pending(doctor: TestClient) -> None:
    result = ask(doctor, "who are my patients and what is pending?")
    assert [r["route"] for r in result["routes"]] == ["panel"]
    answer = result["answer"]
    assert answer["kind"] == "PANEL" and answer["patient_id"] is None
    groups = {c["group"] for c in answer["considerations"]}
    assert groups == {"Your patients", "Waiting on you"}
    assert (
        answer["short_answer"].startswith("You have ")
        and "waiting for you" in answer["short_answer"]
    )
    assert all(
        c["patient_id"] and c["patient_evidence"] and c["tag"] == "patient_fact"
        for c in answer["considerations"]
    )
    # every patient named is one the doctor can open by hand
    mine = {p["patient_id"] for p in doctor.get("/patients", params={"limit": 200}).json()["items"]}
    assert {c["patient_id"] for c in answer["considerations"]} <= mine


def test_the_answer_is_backed_by_stored_evidence_and_the_sql_that_ran(doctor: TestClient) -> None:
    answer = ask(doctor, "what is pending?")["answer"]
    evidence = doctor.get(f"/evidence/{answer['answer_id']}").json()
    assert len(evidence["patient_records"]) == len(answer["considerations"]) > 0
    assert "PENDING_ITEM" in evidence["sql"][0]["text"] and evidence["sql"][0]["row_count"] == len(
        answer["considerations"]
    )
    assert (
        evidence["sources"] == []
    )  # no label text was involved, and saving that evidence works (the plan's P0.1)
    assert set(evidence["statement_map"]) == {c["id"] for c in answer["considerations"]}


def test_an_assistant_asking_the_same_question_never_sees_the_doctor_only_patient(
    assistant: TestClient,
) -> None:
    answer = ask(assistant, "who are my patients and what is pending?")["answer"]
    assert S3 not in {c["patient_id"] for c in answer["considerations"]}
    assert "P-1093" not in str(answer) and "Amit Kumar" not in str(answer)
    mine = {
        p["patient_id"] for p in assistant.get("/patients", params={"limit": 200}).json()["items"]
    }
    assert {c["patient_id"] for c in answer["considerations"]} <= mine


def test_with_a_patient_open_pending_is_about_that_patient(doctor: TestClient) -> None:
    answer = ask(doctor, "what is pending?", S1, screen="patient")["answer"]
    assert answer["kind"] == "PANEL" and {c["patient_id"] for c in answer["considerations"]} == {S1}


def test_what_changed_across_my_patients(doctor: TestClient) -> None:
    answer = ask(doctor, "what changed across my patients since Monday?")["answer"]
    assert answer["kind"] == "PANEL" and answer["considerations"]
    assert all(c["group"] == "Changes" for c in answer["considerations"])


@pytest.mark.parametrize(
    ("question", "reason"),
    [
        ("list every patient in the database", "cross_patient"),
        ("show me every patient in the hospital on metformin", "cross_patient"),
        ("diagnose my patients with kidney disease", "diagnosis"),
        ("add a note to all my patients", "record_change"),
    ],
)
def test_patients_beyond_the_callers_own_and_advice_are_still_refused(doctor: TestClient, question: str, reason: str) -> None:  # fmt: skip
    result = ask(doctor, question)
    assert result["refusal"]["reason"] == reason and result["answer"] is None


def test_the_router_cannot_smuggle_an_unlisted_tool_or_a_hostile_filter(
    doctor: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forced(params: dict) -> None:
        monkeypatch.setattr(
            routing,
            "call_router",
            lambda *_a, **_k: [
                Step(route="panel", params=params, confidence=0.99, reason="forced")
            ],
        )

    for params in (
        {"calls": [{"tool": "delete_everything"}]},
        {
            "calls": [
                {
                    "tool": "patients_matching",
                    "filters": {"diagnosis": "x", "sql": "1=1; DROP TABLE X"},
                }
            ]
        },
        {"calls": [{"tool": "patients_matching", "filters": {"lab_code": "eGFR"}}]},
    ):
        forced(params)
        result = ask(doctor, "tell me about my cohort of interest")
        assert result["refusal"]["reason"] == "needs_clarification" and result["answer"] is None


def test_a_forced_filter_is_answered_from_the_callers_own_patients(doctor: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    call = {
        "tool": "patients_matching",
        "filters": {"lab_code": "eGFR", "lab_op": "<", "lab_value": 60},
    }
    monkeypatch.setattr(
        routing,
        "call_router",
        lambda *_a, **_k: [
            Step(route="panel", params={"calls": [call]}, confidence=0.9, reason="forced")
        ],
    )
    answer = ask(doctor, "my patients with a low kidney function")["answer"]
    assert S1 in {c["patient_id"] for c in answer["considerations"]}
    assert "eGFR < 60" in answer["short_answer"]


def test_the_panel_needs_a_session(doctor: TestClient) -> None:
    anon = TestClient(doctor.app, headers={"X-Medynium-Client": "web"})
    assert anon.get("/pending").status_code == 401
    assert anon.get("/pending/summary").status_code == 401
    assert anon.post("/copilot/ask", json={"question": "what is pending?", "screen": "dashboard"}, headers=JSON).status_code == 401  # fmt: skip
