"""Knowledge search: full citations, brand resolution, honest gaps, conflicts, snapshot (FR-06, M3)."""

import pytest
from fastapi.testclient import TestClient

from medynium_api.main import app
from tests.integration.test_dashboard import signed_in

pytestmark = pytest.mark.snowflake
CITATION_FIELDS = {
    "chunk_id",
    "document_id",
    "title",
    "source",
    "drug",
    "section",
    "version",
    "effective_date",
    "retrieved_date",
    "snippet",
    "text",
    "score",
}


def test_s1_drug_renal_wording_returns_the_right_section_with_every_citation_field(
    users: dict,
) -> None:
    body = (
        signed_in("sharma@demo.medynium")
        .get("/knowledge/search", params={"q": "metformin renal impairment eGFR"})
        .json()
    )
    assert body["snapshot_date"] == "2026-10-02"
    top = body["items"][0]
    assert top["drug"] == "Metformin hydrochloride" and set(top) >= CITATION_FIELDS
    assert top["section"] in {
        "Contraindications",
        "Warnings and precautions",
        "Dosage and administration",
    }
    assert (
        top["version"].startswith("Label version")
        and top["effective_date"]
        and top["retrieved_date"]
    )
    assert "eGFR" in top["text"] and top["source"] == "openFDA drug labeling"


def test_indian_brand_resolves_to_its_generic(users: dict) -> None:
    body = (
        signed_in("sharma@demo.medynium").get("/knowledge/search", params={"q": "Glycomet"}).json()
    )
    assert body["resolved"].get("glycomet") == "Metformin hydrochloride"
    assert body["items"] and all(i["drug"] == "Metformin hydrochloride" for i in body["items"])


def test_conflict_pair_returns_both_sources_flagged(users: dict) -> None:
    body = (
        signed_in("sharma@demo.medynium")
        .get(
            "/knowledge/search",
            params={"q": "furosemide dosage and administration", "drug": "furosemide", "limit": 10},
        )
        .json()
    )
    flagged = [i for i in body["items"] if i["conflict"]]
    assert {i["document_id"] for i in flagged} >= {"DOC-FUR-001", "DOC-FUR-TEST"}
    assert body["conflicts"] and any("TEST DATA" in i["text"] for i in flagged)
    versions = {i["version"] for i in flagged}
    assert len(versions) >= 2


def test_status_reports_the_snapshot_and_corpus(users: dict) -> None:
    body = signed_in("assistant@demo.medynium").get("/knowledge/status").json()
    assert (
        body["snapshot_date"] == "2026-10-02"
        and body["drug_count"] == 26
        and body["document_count"] == 27
    )
    assert "Perampanel" not in str(body["drugs"]) and "Metformin hydrochloride" in body["drugs"]


def test_a_drug_outside_the_corpus_is_a_clean_gap(users: dict) -> None:
    body = (
        signed_in("sharma@demo.medynium")
        .get("/knowledge/search", params={"q": "perampanel seizures"})
        .json()
    )
    assert body["items"] == [] and body["message"] == "No matching section in the indexed sources."


def test_search_requires_a_session_and_a_query() -> None:
    client = TestClient(app)
    assert client.get("/knowledge/search", params={"q": "metformin"}).status_code == 401
    assert signed_in("sharma@demo.medynium").get("/knowledge/search").status_code == 422
