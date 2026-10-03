"""Deterministic safety rules: conclusions made by code from the record alone, not by the model.

A rule never needs label text, so it cannot be skipped because a drug has no indexed label, and it does not vary from
run to run. Each rule returns statements in the same shape as the validated ones, so they appear in the same list
with the same evidence buttons, tagged `rule_check` so they are never mistaken for AI output.
"""

from medynium_api.core.evidence.models import Consideration, EvidenceBundle
from medynium_api.features.copilot.repository import Facts

MIN_PARTIAL = 5  # shortest name that may match inside a longer one ("aspirin" in "aspirin 75 mg")


def names_match(allergen: str, medicine: str) -> bool:
    """Same substance by name: equal, or one contained in the other when it is long enough to be meaningful."""
    a, m = allergen.strip().lower(), medicine.strip().lower()
    if not a or not m:
        return False
    if a == m:
        return True
    shorter, longer = sorted((a, m), key=len)
    return len(shorter) >= MIN_PARTIAL and shorter in longer


def allergy_conflicts(facts: Facts, bundle: EvidenceBundle) -> list[Consideration]:
    """One statement for each recorded allergy whose substance is also a current medicine."""
    medicines = {
        r.record_id: r.evidence_id for r in bundle.patient_records if r.record_type == "Medication"
    }
    allergies = {
        r.record_id: r.evidence_id for r in bundle.patient_records if r.record_type == "Allergy"
    }
    found: list[Consideration] = []
    for allergy in facts.allergies:
        for med in facts.meds:
            name = med["drug_name"] or med.get("description") or ""
            allergy_ref = allergies.get(allergy["allergy_id"])
            med_ref = medicines.get(med["medication_id"])
            if not (allergy_ref and med_ref and names_match(allergy["substance"], name)):
                continue
            reaction = f" ({allergy['reaction']})" if allergy["reaction"] else ""
            found.append(
                Consideration(
                    id="",
                    text=f"The record lists an allergy to {allergy['substance']}{reaction}, and "
                    f"{med['drug_name']} is listed as a current medicine. This may warrant clinician review.",
                    tag="rule_check",
                    patient_evidence=[allergy_ref, med_ref],
                )
            )
    return found
