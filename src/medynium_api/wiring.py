"""Composition root: the one place that connects features to each other. Features never import features, so anything
copilot needs from another feature arrives here as a port, implemented with that feature's own service."""

from medynium_api.core.session import Session
from medynium_api.features.copilot.ports import PatientRef, Ports
from medynium_api.features.patients.repository import PatientRepository
from medynium_api.features.pins.schemas import PinCreate
from medynium_api.features.pins.service import PinService


class AppPorts:
    def find_patients(self, session: Session, query: str, limit: int) -> list[PatientRef]:
        rows, _ = PatientRepository().list_patients(session.snowflake_role, query, False, limit, 0)
        return [
            PatientRef(
                patient_id=r["patient_id"], name=r["full_name"], age=int(r["age_years"]), sex=r["sex"],
                detail=", ".join(__import__("json").loads(r["main_diagnoses"])[:2]) if isinstance(r["main_diagnoses"], str) else None,
            )
            for r in rows
        ]  # fmt: skip

    def pin_evidence(
        self, session: Session, patient_id: str, answer_id: str, evidence_id: str
    ) -> str:
        return (
            PinService()
            .create(
                session,
                patient_id,
                PinCreate(answer_id=answer_id, evidence_id=evidence_id, note=None),
                None,
            )
            .pin_id
        )


def build_ports() -> Ports:
    return AppPorts()
