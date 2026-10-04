"""What copilot needs from other features, as a port. A feature never imports another feature (architecture test),
so the wiring module supplies an implementation at startup. The agent therefore calls the very same services the
UI endpoints use, under the caller's own session (SEC-11)."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from medynium_api.core.session import Session


@dataclass(frozen=True)
class PatientRef:
    patient_id: str
    name: str
    age: int | None = None
    sex: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class ProposalPreview:
    """What the clinician will see before approving: a title, label/value rows, and the checked arguments."""

    title: str
    fields: list[tuple[str, str]]
    args: dict[str, Any] = field(default_factory=dict)


class ProposalInvalid(Exception):
    """The proposal cannot be previewed; the message is shown to the clinician as is."""


class Ports(Protocol):
    def find_patients(self, session: Session, query: str, limit: int) -> list[PatientRef]:
        """Entitled patients matching a name, id or diagnosis. Never returns a patient the caller cannot see."""

    def pin_evidence(
        self, session: Session, patient_id: str, answer_id: str, evidence_id: str
    ) -> str:
        """Create a pin through the same service as the Pin icon; returns the pin id."""

    def preview_proposal(
        self,
        session: Session,
        kind: str,
        patient_id: str,
        args: dict[str, Any],
        last_answer_id: str | None,
    ) -> ProposalPreview:
        """Validate a proposed write with the same models the manual screen uses. Writes nothing."""

    def execute_proposal(
        self, session: Session, kind: str, patient_id: str, args: dict[str, Any], key: str
    ) -> dict[str, Any]:
        """Run an approved proposal through the real write service, as the caller. Returns record_id and tab."""
