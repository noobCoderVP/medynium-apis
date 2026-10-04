"""Similar patients for the open patient, among the caller's own patients only. Entitlement first (a denied patient is
audited and answered like a missing one), then the shared search in core/similar.py under the caller's role. Each search
is audited: who looked for neighbours of whom."""

import time

from medynium_api.core.access import require_patient
from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.config import Settings
from medynium_api.core.errors import ApiError, not_found
from medynium_api.core.session import Session
from medynium_api.core.similar import DISCLAIMER, Match, Mode, find_similar
from medynium_api.core.snowflake.timing import pad
from medynium_api.features.similar.schemas import (
    LabComparison,
    MatchParts,
    SimilarPatient,
    SimilarResponse,
)


def _item(m: Match) -> SimilarPatient:
    p = m.profile
    return SimilarPatient(
        patient_id=p.patient_id, name=p.name, age=p.age, sex=p.sex, score=m.score, parts=MatchParts(**m.parts),
        why=m.why, shared_diagnoses=m.shared_diagnoses, shared_medicines=m.shared_medicines,
        lab_comparison=[LabComparison(**c) for c in m.lab_comparison],
    )  # fmt: skip


class SimilarService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def find(
        self, session: Session, patient_id: str, limit: int, mode: Mode = "blend"
    ) -> SimilarResponse:
        started = time.monotonic()
        try:
            require_patient(session, patient_id)
            result = find_similar(
                session.snowflake_role,
                patient_id,
                limit,
                mode,
                self.settings.similar_weight_embedding,
            )
            if result is None:
                raise not_found()
        except ApiError:
            write_audit(
                session,
                AuditEntry(
                    action="SIMILAR_PATIENTS",
                    patient_id=patient_id,
                    outcome="DENIED",
                    cost_note="no model call",
                ),
            )
            pad(started)
            raise
        write_audit(
            session,
            AuditEntry(
                action="SIMILAR_PATIENTS", patient_id=patient_id, cost_note="vector search, no generating model",
                outcome_detail=f"{len(result.matches)} of {result.candidates} candidates shown",
            ),
            strict=True,
        )  # fmt: skip
        note = None
        if not result.ready:
            note = "This patient was changed a moment ago and is still being prepared. Try again shortly."
        elif len(result.matches) < limit:
            n = len(result.matches)
            note = (
                f"Only {n} similar patient{'s' if n != 1 else ''} among your own patients"
                if n
                else "No similar patients among your own patients"
            ) + ". The list is not padded."
        return SimilarResponse(
            patient_id=patient_id, ready=result.ready, items=[_item(m) for m in result.matches], requested=limit,
            scoring=mode, weight_embedding=self.settings.similar_weight_embedding, note=note, disclaimer=DISCLAIMER,
        )  # fmt: skip
