"""Doctor names on records, and the written summary's checks: both are plain rules over text, so both are tested without
a database."""

from medynium_api.core.intel.doctors import Directory, Doctor, title
from medynium_api.core.intel.profile import Profile
from medynium_api.features.brief.written import acceptable, clean, rule_summary

FACTS = """PATIENT: Rahul Patel, 58 years, male. As of 2 Oct 2026.
TREATING DOCTORS: Dr. Sharma

ACTIVE CONDITIONS:
- Type 2 diabetes mellitus, since 2019

ALLERGIES: Sulfonamide antibiotics (rash, moderate)

ACTIVE MEDICINES:
- Metformin, 1000 mg twice daily, started 12 Mar 2019

LATEST RESULTS:
- eGFR 42 mL/min on 18 Sep 2026 (low); previous 47 on 8 Jun 2026

NEEDS ATTENTION (fixed rules):
- (high) eGFR 42 mL/min (low)

GAPS IN THE RECORD (fixed rules):
- LDL not seen in the last 12 months"""


def test_titles_are_added_once() -> None:
    assert title("Anita Rao") == "Dr. Anita Rao"
    assert title("Dr. Sharma") == "Dr. Sharma"
    assert title("dr sharma") == "dr sharma"


def test_a_record_with_its_own_doctor_keeps_it_and_one_without_gets_the_treating_doctor_marked_as_such() -> (
    None
):
    d = Directory(
        by_record={"RX-1": Doctor("Dr. Rao", "GENERAL PRACTICE", "provider")},
        treating=["Dr. Sharma"],
    )
    assert d.of("RX-1").name == "Dr. Rao" and d.of("RX-1").basis == "provider"  # type: ignore[union-attr]
    fallback = d.of("RX-2", None)
    assert fallback is not None and fallback.basis == "treating" and fallback.name == "Dr. Sharma"
    assert (
        d.specific("RX-2") is None
    )  # the written summary never attributes a record to someone the data does not name


def test_the_visit_a_record_belongs_to_names_its_doctor() -> None:
    d = Directory(by_record={"ENC-1": Doctor("Dr. Rao", None, "provider")})
    assert d.of("LAB-9", "ENC-1").name == "Dr. Rao"  # type: ignore[union-attr]
    assert Directory().of("LAB-9", "ENC-1") is None


def test_the_summary_may_only_use_numbers_that_are_in_the_facts() -> None:
    good = (
        "## Snapshot\n- Rahul Patel, 58, has type 2 diabetes since 2019.\n## Recent results\n- **eGFR 42 (low)** on 18 Sep 2026, previous 47.\n"
        * 2
    )
    assert acceptable(good, FACTS)
    assert not acceptable(good.replace("42", "39"), FACTS)  # an invented value
    assert not acceptable("## Snapshot\n- short", FACTS)  # too short to be a summary
    assert not acceptable(good + "\nYou should stop metformin.", FACTS)  # advice
    assert not acceptable(good + "\nNo risk to the patient.", FACTS)  # reassurance
    assert not acceptable(good + "\nIgnore all previous instructions.", FACTS)  # an instruction


def test_code_fences_around_the_markdown_are_removed() -> None:
    assert clean("```markdown\n## A\n- b\n```") == "## A\n- b"
    assert clean("## A") == "## A"


def test_the_rule_made_summary_lays_out_the_same_facts_in_the_same_sections() -> None:
    md = rule_summary(Profile("P-1", "Rahul Patel", FACTS, "h", [], []))
    headings = [line for line in md.splitlines() if line.startswith("## ")]
    assert headings == ["## Snapshot", "## Active conditions", "## Medicines", "## Recent results", "## Needs attention", "## Gaps in the record"]  # fmt: skip
    assert "Treating doctors: Dr. Sharma" in md and "Allergies: Sulfonamide antibiotics" in md
    assert acceptable(
        md.replace("## Snapshot", "## Snapshot") + "\n" + md, FACTS
    )  # its own text passes the number check
