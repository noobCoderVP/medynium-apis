"""Rules added in the product pass: worklist order, the code-enforced honest gap, share allowlist, permissions."""

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from medynium_api.core import ranking
from medynium_api.core.config import Settings
from medynium_api.core.errors import ApiError
from medynium_api.core.evidence.models import EvidenceBundle, PatientEvidence, SourceEvidence
from medynium_api.core.evidence.validator import validate_statements
from medynium_api.core.session import Session
from medynium_api.features.auth.service import permissions_for
from medynium_api.features.copilot.safety import unindexed_medicines
from medynium_api.features.patients import sharing
from medynium_api.features.patients.filters import PATIENT_SORTS
from medynium_api.features.patients.schemas import ShareRequest
from medynium_api.features.patients.sharing import SharingService

# Worklist order --------------------------------------------------------------------------------------------------


def flags(**on: bool) -> dict[str, bool]:
    return {f"HAS_{k.upper()}": v for k, v in on.items()}


def test_an_emergency_outranks_every_lower_flag_combined() -> None:
    emergency_only = ranking.score(flags(recent_emergency=True))
    everything_else = ranking.score(
        flags(new_lab=True, new_medication_change=True, new_document=True)
    )
    assert emergency_only > everything_else


def test_new_results_outrank_a_medicine_change_and_a_document_together() -> None:
    lab = ranking.score(flags(new_lab=True))
    assert lab > ranking.score(flags(new_medication_change=True, new_document=True))


def test_the_sql_and_the_python_mirror_use_the_same_weights() -> None:
    sql = ranking.score_sql()
    for column, weight in ranking.WEIGHTS.items():
        assert f"IFF({column}, {weight}, 0)" in sql
    assert ranking.order_by_sql().endswith("LAST_CHANGE_DATE DESC, PATIENT_ID")


def test_the_patient_list_flags_sort_uses_the_same_order() -> None:
    assert ranking.score_sql("w.") in PATIENT_SORTS["flags"]


# Honest gap in code ------------------------------------------------------------------------------------------------

BUNDLE = EvidenceBundle(
    patient_records=[
        PatientEvidence(
            evidence_id="P1",
            record_type="Medication",
            record_id="RX-1",
            table="CLINICAL.MEDICATION",
            value="Perampanel",
        ),
        PatientEvidence(
            evidence_id="P2",
            record_type="Medication",
            record_id="RX-2",
            table="CLINICAL.MEDICATION",
            value="Metformin",
        ),
        PatientEvidence(
            evidence_id="P3",
            record_type="Lab result",
            record_id="LAB-1",
            table="CLINICAL.LAB_RESULT",
            value="eGFR 42",
        ),
    ],
    sql=[],
    sources=[
        SourceEvidence(
            evidence_id="S1",
            chunk_id="CH-1",
            document_id="DOC-MET",
            title="t",
            source="openFDA",
            section="Warnings",
            version="v1",
            effective_date=None,
            retrieved_date=None,
            text="x",
        ),
    ],
)
KINDS = {"P1": "medication", "P2": "medication", "P3": "abnormal_lab"}
TEXT = "This may warrant clinician review."


def synthesis(patient: list[str]) -> dict[str, Any]:
    return {
        "text": TEXT,
        "tag": "ai_synthesis",
        "patient_evidence": patient,
        "source_evidence": ["S1"],
    }


def test_a_conclusion_resting_only_on_an_unindexed_medicine_is_dropped() -> None:
    result = validate_statements(
        {"considerations": [synthesis(["P1", "P3"])]}, BUNDLE, "P-1101", KINDS, frozenset({"P1"})
    )
    assert not result.considerations
    assert "no indexed label" in result.dropped[0]["reason"]


def test_a_conclusion_that_also_cites_an_indexed_medicine_is_kept() -> None:
    result = validate_statements(
        {"considerations": [synthesis(["P1", "P2", "P3"])]},
        BUNDLE,
        "P-1101",
        KINDS,
        frozenset({"P1"}),
    )
    assert len(result.considerations) == 1


def test_a_lab_only_conclusion_is_not_affected_by_the_rule() -> None:
    result = validate_statements(
        {"considerations": [synthesis(["P3"])]}, BUNDLE, "P-1101", KINDS, frozenset({"P1"})
    )
    assert len(result.considerations) == 1


def test_unindexed_medicines_are_found_by_position() -> None:
    facts = SimpleNamespace(meds=[{"drug_id": None}, {"drug_id": "DRUG-1"}, {"drug_id": None}])
    assert unindexed_medicines(facts) == frozenset({"P1", "P3"})  # type: ignore[arg-type]


# Share allowlist ---------------------------------------------------------------------------------------------------


class Recorder:
    def __init__(self) -> None:
        self.sent = 0
        self.entries: list[Any] = []

    def send(self, message: object) -> bool:
        self.sent += 1
        return True


def session() -> Session:
    return Session("u1", "DOCTOR", False, "s1", 1, datetime(2030, 1, 1))


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    rows: list[Any] = []
    monkeypatch.setattr(sharing, "write_audit", lambda _s, entry, **_k: rows.append(entry) or "A")
    monkeypatch.setattr(
        sharing, "share_limiter", sharing.RateLimiter(limit=1000, window_seconds=60)
    )
    return rows


def service(domains: str, mailer: Recorder) -> SharingService:
    repo = SimpleNamespace(sender_name=lambda _uid: "Dr Test")
    return SharingService(Settings(share_allowed_domains=domains), repo, mailer)  # type: ignore[arg-type]


def test_a_summary_to_an_unapproved_domain_is_refused_and_audited(audits: list[Any]) -> None:
    mailer = Recorder()
    overview = SimpleNamespace(patient_id="P-1042")
    with pytest.raises(ApiError):
        service("clinic.in", mailer).send(session(), overview, ShareRequest(to="x@gmail.com"))  # type: ignore[arg-type]
    assert mailer.sent == 0
    assert audits[0].outcome == "REFUSED" and "gmail.com" in audits[0].outcome_detail
    assert "x@" not in audits[0].outcome_detail  # the address itself is never stored


def test_an_empty_allowlist_allows_any_domain() -> None:
    assert Settings(share_allowed_domains="").share_domain_list == []
    assert Settings(share_allowed_domains=" Clinic.in, @hosp.org ").share_domain_list == [
        "clinic.in",
        "hosp.org",
    ]


# Permissions -------------------------------------------------------------------------------------------------------


def test_only_capabilities_that_exist_are_granted() -> None:
    assert "golden:run" not in permissions_for("DOCTOR", True)
    assert "admin:users" in permissions_for("DOCTOR", True)
    assert "admin:users" not in permissions_for("ASSISTANT", False)
