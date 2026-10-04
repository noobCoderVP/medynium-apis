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
    assert (
        body["snapshot_date"] >= "2026-10-02"
    )  # the corpus was extended on the day Phase 4 landed
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
        body["snapshot_date"] >= "2026-10-02"
        and body["drug_count"] >= 75
        and body["document_count"] == 69  # 26 + 42 labels, plus the one labelled test document
    )
    assert "Perampanel" not in str(body["drugs"]) and "Metformin hydrochloride" in body["drugs"]


def test_a_drug_outside_the_corpus_is_a_clean_gap(users: dict) -> None:
    body = (
        signed_in("sharma@demo.medynium")
        .get("/knowledge/search", params={"q": "perampanel seizures"})
        .json()
    )
    assert body["items"] == [] and body["message"] == "No matching section in the indexed sources."


def test_topic_words_find_sections_across_drugs(users: dict) -> None:
    body = (
        signed_in("sharma@demo.medynium").get("/knowledge/search", params={"q": "pregnancy"}).json()
    )
    assert body["items"] and body["mode"] == "search"
    for topic in ("renal", "diabetes", "blood pressure"):
        found = (
            signed_in("sharma@demo.medynium").get("/knowledge/search", params={"q": topic}).json()
        )
        assert found["items"], topic


def test_a_topic_about_an_unindexed_drug_stays_a_gap(users: dict) -> None:
    client = signed_in("sharma@demo.medynium")
    for q in ("ivermectin dosing for scabies", "insulin glargine hypoglycemia"):
        assert client.get("/knowledge/search", params={"q": q}).json()["items"] == [], q


def test_a_misspelt_drug_still_resolves(users: dict) -> None:
    body = (
        signed_in("sharma@demo.medynium")
        .get("/knowledge/search", params={"q": "metformn renal"})
        .json()
    )
    assert body["items"] and all(i["drug"] == "Metformin hydrochloride" for i in body["items"])


def test_a_drug_alone_browses_its_sections_and_filters_by_section_in_any_case(users: dict) -> None:
    client = signed_in("sharma@demo.medynium")
    everything = client.get(
        "/knowledge/search", params={"drug": "Warfarin sodium", "limit": 25}
    ).json()
    assert everything["mode"] == "browse" and everything["scope"] == ["Warfarin sodium"]
    assert everything["items"][0]["section"] == "Boxed warning"
    only = client.get(
        "/knowledge/search", params={"drug": "warfarin", "section": "contraindications"}
    ).json()
    assert only["items"] and {i["section"] for i in only["items"]} == {"Contraindications"}


def test_unknown_drug_or_section_is_an_honest_gap(users: dict) -> None:
    client = signed_in("sharma@demo.medynium")
    bad_drug = client.get("/knowledge/search", params={"drug": "Zzzz"}).json()
    assert bad_drug["items"] == [] and "not an indexed drug" in bad_drug["message"]
    bad_section = client.get(
        "/knowledge/search", params={"q": "warfarin", "section": "nonsense"}
    ).json()
    assert bad_section["items"] == [] and "No section named" in bad_section["message"]


def test_drug_directory_lists_brands_and_counts(users: dict) -> None:
    items = signed_in("sharma@demo.medynium").get("/knowledge/drugs").json()["items"]
    metformin = next(d for d in items if d["name"] == "Metformin hydrochloride")
    assert len(items) >= 68 and "glycomet" in metformin["brands"] and metformin["section_count"] > 0


def test_directory_requires_a_session() -> None:
    assert TestClient(app).get("/knowledge/drugs").status_code == 401


def test_search_requires_a_session_and_a_query() -> None:
    client = TestClient(app)
    assert client.get("/knowledge/search", params={"q": "metformin"}).status_code == 401
    assert signed_in("sharma@demo.medynium").get("/knowledge/search").status_code == 422
