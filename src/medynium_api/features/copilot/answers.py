"""Build, store and announce a finished answer. Shared by every route that produces one."""

import datetime as dt

from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.evidence.models import (
    AnswerObject,
    ConflictItem,
    Consideration,
    EvidenceBundle,
    Kind,
    Limits,
    RouteInfo,
)
from medynium_api.core.evidence.store import save_answer
from medynium_api.core.ids import new_id
from medynium_api.core.session import Session
from medynium_api.core.streaming import Run


def finalize(
    session: Session,
    run: Run,
    *,
    kind: Kind,
    patient_id: str | None,
    short_answer: str,
    considerations: list[Consideration],
    limits: Limits,
    conflicts: list[ConflictItem],
    bundle: EvidenceBundle,
    route: RouteInfo,
    question: str | None,
    action: str,
    prompt_hash: str | None = None,
    dropped: list[dict[str, str]] | None = None,
    outcome_detail: str | None = None,
) -> AnswerObject:
    """Store the answer and its evidence, write the audit row (steps equal what was streamed), emit `answer`."""
    cited_patient = sorted({e for c in considerations for e in c.patient_evidence})
    cited_sources = {e for c in considerations for e in c.source_evidence}
    for source in bundle.sources:
        source.matched = source.evidence_id in cited_sources
    answer = AnswerObject(
        answer_id=new_id("ANS", 8), kind=kind, patient_id=patient_id, short_answer=short_answer,
        considerations=considerations, limits=limits, conflicts=conflicts, route=route,
        created_at=dt.datetime.now(dt.UTC).replace(tzinfo=None),
    )  # fmt: skip
    with run.step("Saving the evidence"):
        save_answer(
            session,
            answer,
            bundle,
            question=question,
            model=route.model,
            prompt_hash=prompt_hash,
            dropped=dropped or [],
        )
    run.audit_id = write_audit(
        session,
        AuditEntry(
            action=action, route=route.route, model=route.model, confidence=route.confidence, cost_note=route.cost_note,
            patient_id=patient_id, question=question, answer_id=answer.answer_id, patient_evidence_ids=cited_patient,
            document_ids=sorted({s.document_id for s in bundle.sources if s.matched}), steps=run.steps,
            prompt_hash=prompt_hash, outcome="OK", outcome_detail=outcome_detail,
        ),
        strict=False,
    )  # fmt: skip
    run.emit("answer", answer.model_dump(mode="json"))
    return answer
