"""Drug coverage against the live account (production plan Phase 4, gate G5): what is covered and what is not, honest
answers for a drug with no label, and a request flow that changes nothing until an admin acts."""

import secrets
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from medynium_api.core.security.ratelimit import write_limiter
from tests.integration.purge import clear_drug_requests
from tests.integration.test_dashboard import signed_in

pytestmark = pytest.mark.snowflake


@pytest.fixture(scope="module", autouse=True)
def clean_up() -> Iterator[None]:
    clear_drug_requests()
    yield
    clear_drug_requests()


@pytest.fixture(autouse=True)
def reset_limits() -> None:
    write_limiter.reset()


@pytest.fixture(scope="module")
def doctor(users: dict) -> TestClient:
    return signed_in("sharma@demo.medynium")


@pytest.fixture(scope="module")
def assistant(users: dict) -> TestClient:
    return signed_in("assistant@demo.medynium")


@pytest.fixture(scope="module")
def other(users: dict) -> TestClient:
    return signed_in("second.doctor@demo.medynium")  # a doctor who is not an admin


def made_up() -> str:
    return f"Zz test drug {secrets.token_hex(3)}"


# Honest answers --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "question",
    ["gliclazide hypoglycemia", "Diamicron", "teneligliptin dosing", "domperidone QT prolongation"],
)
def test_a_known_drug_with_no_label_is_an_explicit_gap_never_another_drugs_text(
    doctor: TestClient, question: str
) -> None:
    body = doctor.get("/knowledge/search", params={"q": question}).json()
    assert body["items"] == []
    assert "no label is indexed" in body["message"] and "Nothing is guessed" in body["message"]


def test_the_new_india_drugs_and_their_brands_are_found(doctor: TestClient) -> None:
    for query, drug in [
        ("Augmentin", "Amoxicillin and clavulanate potassium"),
        ("Crocin", "Paracetamol (acetaminophen)"),
        ("Glycomet", "Metformin hydrochloride"),
    ]:
        items = doctor.get("/knowledge/search", params={"q": query}).json()["items"]
        assert items and items[0]["drug"] == drug, query
    sections = doctor.get("/knowledge/search", params={"drug": "Ecosprin"}).json()["items"]
    assert (
        sections
        and {c["drug"] for c in sections} == {"Aspirin"}
        and all(c["source"] == "openFDA drug labeling" for c in sections)
    )


def test_the_status_lists_what_is_not_indexed(doctor: TestClient) -> None:
    status = doctor.get("/knowledge/status").json()
    assert (
        len(status["drugs"]) >= 68
        and "Gliclazide" in status["not_indexed"]
        and "Gliclazide" not in status["drugs"]
    )
    assert status["drug_count"] == len(status["drugs"]) + len(status["not_indexed"])


# Requests --------------------------------------------------------------------------------------------------------
def test_a_clinician_can_ask_for_a_drug_and_asking_twice_is_one_request(
    doctor: TestClient, other: TestClient
) -> None:
    name = made_up()
    first = doctor.post("/knowledge/requests", json={"drug": name, "note": "common in my clinic"})
    assert (
        first.status_code == 201
        and first.json()["status"] == "OPEN"
        and first.json()["already_open"] is False
    )
    again = doctor.post("/knowledge/requests", json={"drug": name.upper()})
    assert (
        again.json()["request_id"] == first.json()["request_id"]
        and again.json()["already_open"] is True
    )
    mine = [r["drug"] for r in doctor.get("/knowledge/requests").json()["items"]]
    assert name in mine
    assert name not in [
        r["drug"] for r in other.get("/knowledge/requests").json()["items"]
    ]  # each user sees their own


def test_asking_for_a_drug_that_is_already_indexed_points_to_search(doctor: TestClient) -> None:
    refused = doctor.post("/knowledge/requests", json={"drug": "Metformin"})
    assert refused.status_code == 409 and "already indexed" in refused.json()["message"]
    assert doctor.post("/knowledge/requests", json={"drug": "x"}).status_code == 422


def test_an_assistant_can_ask_but_only_an_admin_sees_and_decides(
    doctor: TestClient, assistant: TestClient, other: TestClient
) -> None:
    name = made_up()
    made = assistant.post("/knowledge/requests", json={"drug": name})
    assert made.status_code == 201
    rid = made.json()["request_id"]
    for client in (assistant, other):
        assert client.get("/admin/knowledge/requests").status_code == 403
        assert client.get("/admin/knowledge/coverage").status_code == 403
        assert (
            client.patch(f"/admin/knowledge/requests/{rid}", json={"status": "ADDED"}).status_code
            == 403
        )
    queue = doctor.get("/admin/knowledge/requests", params={"status": "OPEN"}).json()["items"]
    mine = next(r for r in queue if r["request_id"] == rid)
    assert mine["requested_by_name"] == "Meera Joshi"
    done = doctor.patch(
        f"/admin/knowledge/requests/{rid}",
        json={"status": "DECLINED", "note": "no US label exists"},
    )
    assert (
        done.status_code == 200
        and done.json()["status"] == "DECLINED"
        and done.json()["decided_by_name"] == "Dr. Sharma"
    )
    assert (
        doctor.patch(f"/admin/knowledge/requests/{rid}", json={"status": "ADDED"}).status_code
        == 409
    )
    assert (
        doctor.patch("/admin/knowledge/requests/DRQ-NOPE", json={"status": "ADDED"}).status_code
        == 404
    )
    assert rid not in [
        r["request_id"]
        for r in doctor.get("/admin/knowledge/requests", params={"status": "OPEN"}).json()["items"]
    ]


def test_requests_need_a_session(doctor: TestClient) -> None:
    anon = TestClient(doctor.app, headers={"X-Medynium-Client": "web"})
    assert anon.post("/knowledge/requests", json={"drug": "something"}).status_code == 401
    assert anon.get("/admin/knowledge/coverage").status_code == 401


# Coverage --------------------------------------------------------------------------------------------------------
def test_the_coverage_report_matches_the_corpus_and_ranks_unlabelled_medicines(
    doctor: TestClient,
) -> None:
    report = doctor.get("/admin/knowledge/coverage").json()
    status = doctor.get("/knowledge/status").json()
    assert (
        report["drugs_indexed"] == len(status["drugs"])
        and report["drugs_known"] == status["drug_count"]
    )
    assert (
        report["not_indexed"] == status["not_indexed"]
        and report["chunks"] == status["chunk_count"] > 700
    )
    assert 0 < report["nlem_indexed"] <= report["nlem_known"]
    counts = [m["patients"] for m in report["unlabelled_in_use"]]
    assert counts == sorted(counts, reverse=True) and all(c > 0 for c in counts)
    assert "US" in report["note"] and "never answered from another drug" in report["note"]
