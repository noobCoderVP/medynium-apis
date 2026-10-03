"""What copilot needs from other features, as a port. A feature never imports another feature (architecture test),
so the wiring module supplies an implementation at startup. The agent therefore calls the very same services the
UI endpoints use, under the caller's own session (SEC-11)."""

from dataclasses import dataclass
from typing import Protocol

from medynium_api.core.session import Session


@dataclass(frozen=True)
class PatientRef:
    patient_id: str
    name: str
    age: int | None = None
    sex: str | None = None
    detail: str | None = None


class Ports(Protocol):
    def find_patients(self, session: Session, query: str, limit: int) -> list[PatientRef]:
        """Entitled patients matching a name, id or diagnosis. Never returns a patient the caller cannot see."""

    def pin_evidence(
        self, session: Session, patient_id: str, answer_id: str, evidence_id: str
    ) -> str:
        """Create a pin through the same service as the Pin icon; returns the pin id."""
