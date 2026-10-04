"""refuse: a scoped refusal in plain words, plus documented considerations where they help (AI-01, AI-04, AI-10).
No model call; the refusal text is fixed so it can never drift into advice."""

from typing import Any

from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.streaming import Run
from medynium_api.features.copilot.handlers import Ctx
from medynium_api.features.copilot.pack import focus_terms

MESSAGES = {
    "prescribing": (
        "I can't recommend, start, stop or dose a medicine, or make a diagnosis. That is the clinician's decision. "
        "What I can do is show documented considerations from the indexed sources for you to review."
    ),
    "cross_patient": (
        "I can answer about the patient you have open, or about your own patients as a group: who needs attention, "
        "what is pending, what changed, who is on a medicine. I can't look at patients you don't have, or at the "
        "whole system. Rephrase it about your own patients, or open a patient and ask."
    ),
    "record_change": (
        "I can't change the clinical record. I can open a patient, show a timeline or lab trend, run the safety review, "
        "or pin evidence."
    ),
    "unlisted_action": (
        "That isn't something I can do. I can open a patient, show a timeline or lab trend, run the safety review, "
        "or pin evidence."
    ),
    "needs_clarification": "I wasn't sure what you meant. Name the patient or ask a specific question, and I will try again.",
    "needs_patient": "Open a patient first, then ask again. I answer about the patient you have open.",
}
OUTCOME = {"needs_clarification": "OK", "needs_patient": "OK"}


def considerations_for(ctx: Ctx) -> list[dict[str, Any]]:
    """Up to three documented considerations for the open patient's medicines. Retrieval only, no generation."""
    if not ctx.patient_id:
        return []
    facts = ctx.repo.patient_facts(ctx.session.snowflake_role, ctx.patient_id)
    if facts is None:
        return []
    drugs = {m["drug_id"]: m["drug_name"] for m in facts.meds if m["drug_id"]}
    if not drugs:
        return []
    found = ctx.search.retrieve_for_patient(drugs, focus_terms(facts), per_drug=1, total=3)
    return [
        {"text": c.text[:300], "drug": c.drug_name, "section": c.section, "document_id": c.document_id, "title": c.title,
         "version": c.version, "effective_date": str(c.effective_date or "")}
        for c in found.chunks
    ]  # fmt: skip


def run_refuse(ctx: Ctx, run: Run, reason: str) -> None:
    with run.step("Checking what I can help with"):
        extra = considerations_for(ctx) if reason == "prescribing" else []
    run.emit(
        "refusal",
        {
            "message": MESSAGES.get(reason, MESSAGES["unlisted_action"]),
            "reason": reason,
            "considerations": extra,
        },
    )
    run.audit_id = write_audit(
        ctx.session,
        AuditEntry(
            action="ASK", route="refuse", model=ctx.info.model, confidence=ctx.info.confidence, cost_note="no model call",
            patient_id=ctx.patient_id, question=ctx.question, steps=run.steps,
            outcome=OUTCOME.get(reason, "REFUSED"), outcome_detail=reason,
        ),
    )  # fmt: skip
