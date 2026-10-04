"""Write proposals (agentic upgrade, phase B2): nothing is written until an approved preview, and only by its owner."""

import datetime as dt
import time
from typing import Any

import pytest

from medynium_api.core.config import Settings
from medynium_api.core.errors import ApiError
from medynium_api.core.session import Session
from medynium_api.features.copilot import approvals, proposals
from medynium_api.features.copilot.ports import ProposalPreview
from medynium_api.features.copilot.proposals import clean_args, grounded
from medynium_api.features.copilot.routing import guard
from medynium_api.features.copilot.service import CopilotService


def _session(user: str = "u1", role: str = "DOCTOR") -> Session:
    return Session(user, role, False, "s", 1, dt.datetime.now(dt.UTC))  # type: ignore[arg-type]


class FakePorts:
    def __init__(self) -> None:
        self.executed: list[tuple[str, str, dict[str, Any], str]] = []

    def execute_proposal(self, session: Session, kind: str, patient_id: str, args: dict[str, Any], key: str) -> dict[str, Any]:  # fmt: skip
        self.executed.append((kind, patient_id, args, key))
        return {"record_id": "R-1", "tab": "notes"}


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch) -> tuple[CopilotService, FakePorts]:
    monkeypatch.setattr(approvals, "write_audit", lambda *a, **k: "AUD-1")
    monkeypatch.setattr(approvals, "require_patient", lambda *a, **k: None)
    ports = FakePorts()
    return CopilotService(Settings(), ports), ports  # type: ignore[arg-type]


def _propose(user: str = "u1") -> str:
    preview = ProposalPreview("Add a clinical note", [("Title", "t")], {"title": "t", "body": "b"})
    return proposals.store.add(
        user, "P-1", "add_note", preview.args, preview.title, preview.fields, "q"
    ).proposal_id


def test_free_text_must_come_from_the_question() -> None:
    q = "record a penicillin allergy, rash, moderate"
    assert grounded("penicillin", q) and grounded("rash", q)
    assert not grounded("sulfonamide anaphylaxis", q)
    assert clean_args(
        {
            "substance": "penicillin",
            "reaction": "anaphylaxis to everything",
            "severity": "MODERATE",
        },
        q,
    ) == {
        "substance": "penicillin",
        "severity": "MODERATE",
    }


def test_nested_or_oversized_arguments_are_rejected() -> None:
    assert clean_args({"a": {"b": 1}}, "q") is None
    assert clean_args({"body": "x" * 5000}, "q") is None
    assert clean_args("not a dict", "q") is None


def test_adding_is_not_blocked_by_the_rule_guard_but_editing_and_deleting_are() -> None:
    assert guard("add a note: patient reports dizziness") is None
    assert guard("record a penicillin allergy") is None
    assert guard("change her metformin dose to 500 mg") == "record_change"
    assert guard("delete the last note") == "record_change"
    assert guard("update the diagnosis") == "record_change"


def test_a_proposal_is_visible_only_to_its_owner_and_expires() -> None:
    pid = _propose("owner")
    assert proposals.store.get(pid, "owner") is not None
    assert proposals.store.get(pid, "someone-else") is None
    proposals.store.get(pid, "owner").created = time.monotonic() - proposals.TTL_SECONDS - 1  # type: ignore[union-attr]
    assert proposals.store.get(pid, "owner") is None


def test_approving_writes_once_through_the_real_service_with_the_proposal_id_as_key(svc: tuple[CopilotService, FakePorts]) -> None:  # fmt: skip
    service_, ports = svc
    pid = _propose()
    first = service_.approve_proposal(_session(), pid)
    second = service_.approve_proposal(_session(), pid)
    assert first == second and first["record_id"] == "R-1" and first["patient_id"] == "P-1"
    assert len(ports.executed) == 1 and ports.executed[0][3] == pid


def test_an_assistant_cannot_approve(svc: tuple[CopilotService, FakePorts]) -> None:
    service_, ports = svc
    with pytest.raises(ApiError) as caught:
        service_.approve_proposal(_session(role="ASSISTANT"), _propose())
    assert caught.value.code.value == "forbidden" and not ports.executed


def test_someone_elses_or_unknown_proposal_is_not_found_and_nothing_is_written(svc: tuple[CopilotService, FakePorts]) -> None:  # fmt: skip
    service_, ports = svc
    for pid in (_propose("other"), "PRP-NOPE"):
        with pytest.raises(ApiError) as caught:
            service_.approve_proposal(_session("u1"), pid)
        assert caught.value.code.value == "not_found"
    assert not ports.executed


def test_a_discarded_proposal_can_no_longer_be_approved(
    svc: tuple[CopilotService, FakePorts],
) -> None:
    service_, ports = svc
    pid = _propose()
    assert service_.discard_proposal(_session(), pid)["status"] == "discarded"
    with pytest.raises(ApiError):
        service_.approve_proposal(_session(), pid)
    assert not ports.executed
