"""Asking about an uploaded report and asking for a live label, through the assistant, against the live account.

Each run uploads a one-page lab report for a fresh "Zz Test" patient and waits for it to be read (the reading model is
live), then asks questions about it. The answers must quote the report with its page, stay inside that patient, and
treat the page text as data."""

import secrets
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from medynium_api.core.security.ratelimit import upload_limiter, write_limiter
from tests.integration.purge import purge_test_patients
from tests.integration.test_copilot import S1, ask
from tests.integration.test_dashboard import signed_in

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data" / "sample_reports"))
from pdfmaker import lab_panel

pytestmark = pytest.mark.snowflake


@pytest.fixture(scope="module", autouse=True)
def clean_up() -> Iterator[None]:
    purge_test_patients()
    yield
    purge_test_patients()


@pytest.fixture(scope="module")
def doctor(users: dict) -> TestClient:
    upload_limiter.reset()
    write_limiter.reset()
    return signed_in("sharma@demo.medynium")


@pytest.fixture(scope="module")
def read_report(doctor: TestClient) -> dict:
    name = f"Zz Test {secrets.token_hex(3)}"
    made = doctor.post(
        "/patients", json={"full_name": name, "birth_date": "1970-02-02", "sex": "M"}
    ).json()
    pid = made["patient_id"]
    pdf = lab_panel(name, "12/09/2026 08:15", [("HbA1c", "8.1", "%", "ref < 7.0"), ("Potassium", "5.4", "mmol/L", "ref 3.5 - 5.0")])  # fmt: skip
    sent = doctor.post(f"/patients/{pid}/reports", content=pdf, headers={"X-Filename": "city-labs.pdf", "Content-Type": "application/pdf"})  # fmt: skip
    assert sent.status_code == 202, sent.text
    report_id = sent.json()["report_id"]
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        body = doctor.get(f"/patients/{pid}/reports/{report_id}").json()
        if body["status"] in ("EXTRACTED", "FAILED"):
            assert body["status"] == "EXTRACTED", body["status_detail"]
            return {"patient_id": pid, "report_id": report_id}
        time.sleep(2)
    raise AssertionError("the report was not read in time")


def test_the_assistant_quotes_the_report_with_its_page(
    doctor: TestClient, read_report: dict
) -> None:
    result = ask(
        doctor, "What does the city-labs report say about potassium?", read_report["patient_id"]
    )
    answer = result["answer"]
    assert answer and answer["patient_id"] == read_report["patient_id"], result
    evidence = doctor.get(f"/evidence/{answer['answer_id']}").json()
    pages = [r for r in evidence["patient_records"] if r["table"] == "CLINICAL.REPORT"]
    assert (
        pages and "city-labs.pdf, page 1" in pages[0]["value"] and "otassium" in pages[0]["value"]
    )
    known = {r["evidence_id"] for r in evidence["patient_records"]}
    assert all(set(c["patient_evidence"]) <= known for c in answer["considerations"])


def test_asking_for_a_report_the_patient_does_not_have_says_so(doctor: TestClient) -> None:
    result = ask(doctor, "Summarize the latest report", S1)
    assert result["answer"] and "no read report" in result["answer"]["short_answer"].lower()


def test_a_report_of_one_patient_is_not_readable_from_another(
    doctor: TestClient, read_report: dict
) -> None:
    result = ask(doctor, "What does the city-labs report say?", S1)
    answer = result["answer"]
    assert answer and answer["patient_id"] == S1
    evidence = doctor.get(f"/evidence/{answer['answer_id']}").json()
    assert not any(r["table"] == "CLINICAL.REPORT" for r in evidence["patient_records"])


def test_the_live_label_is_marked_live_and_never_stored_as_the_snapshot(doctor: TestClient) -> None:
    result = ask(doctor, "check the live FDA label for ivermectin", S1)
    answer = result["answer"]
    assert answer and answer["kind"] == "KNOWLEDGE"
    evidence = doctor.get(f"/evidence/{answer['answer_id']}").json()
    assert evidence["sources"] and all(
        s["source"] == "openFDA live API" for s in evidence["sources"]
    )
    assert any("live from openFDA" in n for n in answer["limits"]["notes"])
