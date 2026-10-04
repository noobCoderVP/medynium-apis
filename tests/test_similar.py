"""Similar-patient scoring without Snowflake: what counts as the same condition, how the two signals blend, and that every
match carries reasons taken from the records."""

import pytest

from medynium_api.core.similar import (
    MIN_SCORE,
    Profile,
    age_closeness,
    blend,
    compare,
    embedding_part,
    jaccard,
    lab_agreement,
    normalise,
)


def profile(pid: str, age: int, dx: list[str], rx: list[str], labs: dict | None = None) -> Profile:
    return Profile(
        pid, f"Patient {pid}", age, "M",
        {normalise(d): d for d in dx}, {normalise(r): r for r in rx}, labs or {},
    )  # fmt: skip


KIDNEY = profile(
    "A", 58, ["Chronic kidney disease, stage 3b", "Type 2 diabetes mellitus"], ["Metformin", "Lisinopril"],
    {"eGFR": (42.0, "mL/min", "LOW"), "HbA1c": (8.1, "%", "HIGH")},
)  # fmt: skip


def test_the_same_condition_matches_across_wording_and_stage() -> None:
    assert (
        normalise("Chronic kidney disease, stage 3b")
        == normalise("Chronic kidney disease stage 2")
        == "chronic kidney disease"
    )
    assert normalise("Hypertension (disorder)") == "hypertension"
    assert normalise("Type 2 diabetes mellitus") != normalise(
        "Diabetes mellitus type 2"
    )  # embeddings cover this gap


def test_overlap_measures() -> None:
    assert jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)
    assert jaccard(set(), set()) == 0.0
    assert (
        embedding_part(0.30) == 0
        and embedding_part(0.90) == 1
        and embedding_part(0.6) == pytest.approx(0.5)
    )
    assert embedding_part(0.1) == 0 and embedding_part(0.99) == 1


def test_labs_agree_when_the_same_tests_are_abnormal_the_same_way() -> None:
    same = profile("B", 60, [], [], {"eGFR": (45.0, "mL/min", "LOW"), "HbA1c": (8.5, "%", "HIGH")})
    opposite = profile("C", 60, [], [], {"eGFR": (110.0, "mL/min", "HIGH")})
    neither = profile("D", 60, [], [], {"eGFR": (90.0, "mL/min", "NORMAL")})
    assert lab_agreement(KIDNEY, same) == 1.0
    assert lab_agreement(KIDNEY, opposite) == 0.0
    assert (
        lab_agreement(neither, neither) == 0.5
    )  # no abnormal result on either side says nothing either way


def test_age_closeness_falls_with_distance() -> None:
    assert age_closeness(KIDNEY, profile("B", 58, [], [])) == 1.0
    assert age_closeness(KIDNEY, profile("B", 73, [], [])) == pytest.approx(0.5)
    assert age_closeness(KIDNEY, profile("B", 99, [], [])) == 0.0


def test_a_close_case_outranks_a_distant_one_and_says_why() -> None:
    close = profile(
        "B", 61, ["Chronic kidney disease, stage 3a", "Type 2 diabetes mellitus"], ["Metformin", "Ramipril"],
        {"eGFR": (45.0, "mL/min", "LOW")},
    )  # fmt: skip
    far = profile("C", 6, ["Asthma"], ["Salbutamol"])
    a = compare(KIDNEY, close, cosine=0.85)
    b = compare(KIDNEY, far, cosine=0.35)
    assert a.score > 0.5 > b.score
    assert b.score < MIN_SCORE or b.score < a.score
    assert a.shared_diagnoses == ["Chronic kidney disease, stage 3b", "Type 2 diabetes mellitus"]
    assert a.shared_medicines == ["Metformin"]
    assert a.lab_comparison == [
        {
            "test": "eGFR",
            "this_value": 42.0,
            "other_value": 45.0,
            "unit": "mL/min",
            "this_flag": "LOW",
            "other_flag": "LOW",
        }
    ]
    assert (
        a.why[0].startswith("Both have Chronic kidney disease") and "both on Metformin" in a.why[1]
    )
    assert "eGFR 42 vs 45 mL/min" in a.why


def test_a_match_with_nothing_shared_is_honest_about_it() -> None:
    odd = compare(KIDNEY, profile("E", 58, ["Asthma"], ["Salbutamol"]), cosine=0.55)
    assert odd.shared_diagnoses == [] and odd.shared_medicines == []
    assert odd.why == ["Similar overall case picture, but no shared diagnosis or medicine"]


def test_the_three_scoring_modes() -> None:
    other = profile("B", 61, ["Type 2 diabetes mellitus"], ["Metformin"])
    parts = compare(KIDNEY, other, cosine=0.9).parts
    structured = blend(parts, parts["embedding"], "structured", 0.5)
    only_embedding = blend(parts, parts["embedding"], "embedding", 0.5)
    mixed = blend(parts, parts["embedding"], "blend", 0.5)
    assert only_embedding == 1.0 and 0 < structured < 1
    assert mixed == pytest.approx(0.5 * only_embedding + 0.5 * structured)
    assert blend(parts, parts["embedding"], "blend", 1.0) == only_embedding
    assert blend(parts, parts["embedding"], "blend", 0.0) == structured
