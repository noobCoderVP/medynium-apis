"""Drug, brand and section matching for knowledge search (no Snowflake needed)."""

from medynium_api.features.knowledge.names import match_drugs, match_sections, suggest_drugs

ALIASES = [
    {"name_text": "metformin", "name_kind": "SYNTHEA_INGREDIENT", "drug_id": "D1", "display_name": "Metformin hydrochloride"},
    {"name_text": "glycomet", "name_kind": "INDIAN_BRAND", "drug_id": "D1", "display_name": "Metformin hydrochloride"},
    {"name_text": "amlodipine", "name_kind": "SYNTHEA_INGREDIENT", "drug_id": "D2", "display_name": "Amlodipine besylate"},
    {"name_text": "warfarin sodium", "name_kind": "ALTERNATE_GENERIC", "drug_id": "D3", "display_name": "Warfarin sodium"},
]  # fmt: skip
SECTIONS = ["Boxed warning", "Contraindications", "Warnings", "Warnings and precautions"]


def ids(text: str) -> set[str]:
    return {m["drug_id"] for m in match_drugs(text, ALIASES)}


def test_exact_brand_and_two_word_names_match() -> None:
    assert ids("Glycomet dose") == {"D1"}
    assert ids("warfarin sodium bleeding") == {"D3"}


def test_prefix_and_small_typos_match() -> None:
    assert ids("amlodipin") == {"D2"}
    assert ids("amlod") == {"D2"}
    assert ids("metformn renal") == {"D1"}


def test_topic_words_and_short_words_match_nothing() -> None:
    assert ids("renal impairment") == set()
    assert ids("dose") == set()
    assert ids("hello world") == set()


def test_suggestions_offer_the_nearest_indexed_drug() -> None:
    names = ["Metformin hydrochloride", "Warfarin sodium"]
    assert suggest_drugs("metfor", names) == ["Metformin hydrochloride"]
    assert suggest_drugs("warfrin", names) == ["Warfarin sodium"]
    assert suggest_drugs("zzzz", names) == []


def test_section_matches_any_case_and_related_headings() -> None:
    assert match_sections("contraindications", SECTIONS) == ["Contraindications"]
    assert match_sections("Warnings", SECTIONS) == [
        "Warnings",
        "Boxed warning",
        "Warnings and precautions",
    ]
    assert match_sections("warning", SECTIONS)[0] == "Boxed warning"
    assert match_sections("pharmacology", SECTIONS) == []
