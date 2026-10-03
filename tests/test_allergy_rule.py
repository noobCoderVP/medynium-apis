"""The allergy-to-medicine rule is code, not model output (product plan E6)."""

import pytest

from medynium_api.core.evidence.models import EvidenceBundle
from medynium_api.core.evidence.validator import Validated, short_answer, validate_statements
from medynium_api.features.copilot.pack import patient_evidence
from medynium_api.features.copilot.repository import Facts
from medynium_api.features.copilot.rules import allergy_conflicts, names_match


def facts(allergies: list[dict], meds: list[dict]) -> Facts:
    return Facts(
        patient_id="P-1", name="X", diagnoses=[], meds=meds, labs=[], notes=[], allergies=allergies
    )


def med(medication_id: str, name: str) -> dict:
    return {
        "medication_id": medication_id, "drug_id": "D1", "drug_name": name, "dose_text": "75 mg",
        "start_date": None, "last_change_date": None, "change_note": None, "description": name,
    }  # fmt: skip


def allergy(allergy_id: str, substance: str, reaction: str | None = "Hives") -> dict:
    return {
        "allergy_id": allergy_id,
        "substance": substance,
        "reaction": reaction,
        "severity": "SEVERE",
    }


def bundle_for(f: Facts) -> EvidenceBundle:
    records, _, _ = patient_evidence(f)
    return EvidenceBundle(patient_records=records)


@pytest.mark.parametrize(
    ("allergen", "medicine", "expected"),
    [
        ("Aspirin", "aspirin", True),
        ("Aspirin", "Aspirin 75 mg tablet", True),
        ("Penicillin", "Amoxicillin", False),  # related, but this rule matches names only
        ("Sulfonamide antibiotics", "Metformin", False),
        ("Ace", "Lisinopril", False),  # too short to match inside a longer name
        ("", "Aspirin", False),
    ],
)
def test_names_match(allergen: str, medicine: str, expected: bool) -> None:
    assert names_match(allergen, medicine) is expected


def test_a_matching_allergy_gives_one_rule_check_citing_both_records() -> None:
    f = facts([allergy("ALG-1", "Aspirin")], [med("RX-1", "Aspirin"), med("RX-2", "Atorvastatin")])
    hits = allergy_conflicts(f, bundle_for(f))
    assert len(hits) == 1
    assert hits[0].tag == "rule_check" and "may warrant clinician review" in hits[0].text
    cited = {"P1", "P3"}  # Aspirin is P1; the allergy is added after the two medicines
    assert set(hits[0].patient_evidence) == cited and hits[0].source_evidence == []


def test_no_match_no_statement_and_no_allergies_no_statement() -> None:
    f = facts([allergy("ALG-1", "Penicillin")], [med("RX-1", "Metformin")])
    assert allergy_conflicts(f, bundle_for(f)) == []
    g = facts([], [med("RX-1", "Metformin")])
    assert allergy_conflicts(g, bundle_for(g)) == []


def test_medicines_keep_the_first_evidence_ids_when_allergies_exist() -> None:
    f = facts([allergy("ALG-1", "Aspirin")], [med("RX-1", "Aspirin"), med("RX-2", "Atorvastatin")])
    records, _, kinds = patient_evidence(f)
    assert [r.evidence_id for r in records if r.record_type == "Medication"] == ["P1", "P2"]
    assert kinds["P3"] == "allergy"


def test_the_model_cannot_produce_a_rule_check() -> None:
    f = facts([allergy("ALG-1", "Aspirin")], [med("RX-1", "Aspirin")])
    draft = {"considerations": [{"text": "Fake.", "tag": "rule_check", "patient_evidence": ["P1"]}]}
    result = validate_statements(draft, bundle_for(f), "P-1")
    assert not result.considerations and result.dropped[0]["reason"] == "unknown tag"


def test_a_rule_hit_is_counted_in_the_short_answer() -> None:
    assert "1 documented consideration" in short_answer(
        Validated(considerations=[], rule_hits=1), []
    )
