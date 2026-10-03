"""Pinning evidence to a patient workspace. Same function behind the Pin icon and the pin_evidence action."""

from typing import Any

from medynium_api.core.access import require_patient
from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.errors import not_found
from medynium_api.core.ids import new_id
from medynium_api.core.session import Session
from medynium_api.features.pins.repository import PinRepository
from medynium_api.features.pins.schemas import Pin, PinCreate, PinList


def _pin(row: dict[str, Any]) -> Pin:
    return Pin(
        pin_id=row["pin_id"], answer_id=row["answer_id"], evidence_id=row["evidence_id"], label=row["label"],
        note=row["note"], created_at=row["created_at"],
    )  # fmt: skip


class PinService:
    def __init__(self, repo: PinRepository | None = None) -> None:
        self.repo = repo or PinRepository()

    def list_pins(self, session: Session, patient_id: str) -> PinList:
        require_patient(session, patient_id)
        return PinList(
            items=[_pin(r) for r in self.repo.list_pins(session.snowflake_role, patient_id)]
        )

    def create(self, session: Session, patient_id: str, body: PinCreate, key: str | None) -> Pin:
        require_patient(session, patient_id)
        row = self.repo.create(
            session.snowflake_role, session.user_id, patient_id, body.answer_id, body.evidence_id, body.note,
            new_id("PIN", 8), key,
        )  # fmt: skip
        if row is None:
            raise not_found()
        write_audit(
            session,
            AuditEntry(
                action="PIN_EVIDENCE",
                patient_id=patient_id,
                answer_id=body.answer_id,
                cost_note="no model call",
            ),
        )
        return _pin(row)

    def delete(self, session: Session, patient_id: str, pin_id: str) -> None:
        require_patient(session, patient_id)
        if self.repo.delete(session.snowflake_role, patient_id, pin_id) == 0:
            raise not_found()
