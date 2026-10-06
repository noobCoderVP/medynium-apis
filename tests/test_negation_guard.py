"""Negation and family-history guard (SRS AI rules): offline checks that the seed, the prompts and the golden set agree."""

from pathlib import Path

import yaml

from medynium_api.features.copilot.pack import patient_evidence
from medynium_api.features.copilot.repository import Facts

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "src" / "medynium_api" / "features" / "copilot" / "prompts"


def seeded_note() -> str:
    data = yaml.safe_load((ROOT / "data/scenarios/scenarios.yaml").read_text(encoding="utf-8"))
    control = next(p for p in data["patients"] if p["id"] == "P-1067")
    return next(n["body"] for n in control["notes"] if n["id"] == "DOC-OP-20885")


def test_control_patient_note_has_negation_and_family_history() -> None:
    body = seeded_note().lower()
    assert "no history of kidney disease" in body
    assert "mother had chronic kidney disease" in body


def test_negated_mention_never_becomes_a_diagnosis_record() -> None:
    facts = Facts(
        patient_id="P-1067", name="X", diagnoses=[], meds=[], labs=[], allergies=[],
        notes=[{"note_id": "DOC-OP-20885", "title": "Family history", "note_date": None, "body": seeded_note()}],
    )  # fmt: skip
    records, _, kinds = patient_evidence(facts)
    assert [r for r in records if "kidney" in r.value.lower()]
    assert all(r.record_type == "Note" and r.table == "CLINICAL.CLINICAL_NOTE" for r in records)
    assert "diagnosis" not in kinds


def test_both_prompts_carry_the_polarity_rule() -> None:
    for name in ("composer.md", "safety_agent.md"):
        text = (PROMPTS / name).read_text(encoding="utf-8")
        assert "polarity" in text and "Mother had X" in text, name


def test_golden_set_has_negation_cases_with_forbidden_claims() -> None:
    cases = yaml.safe_load((ROOT / "evals/golden_set.yaml").read_text(encoding="utf-8"))["cases"]
    neg = [c for c in cases if c["group"] == "negation"]
    assert len(neg) >= 3
    assert all(c["expect"].get("not_contains") for c in neg)
    assert {c["id"] for c in cases} == {f"G{i:02d}" for i in range(1, len(cases) + 1)}
