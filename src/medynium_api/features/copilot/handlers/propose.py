"""propose: prepare a write for the clinician's approval. Nothing is saved here (agentic upgrade, phase B2).

The arguments are checked twice: free text must come from the clinician's own words, and the same models the manual
screen uses validate the rest. The result is a preview card; only the Approve click writes, through the real service."""

from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.streaming import Run
from medynium_api.features.copilot.handlers import Ctx
from medynium_api.features.copilot.handlers.refuse import run_refuse
from medynium_api.features.copilot.ports import ProposalInvalid
from medynium_api.features.copilot.proposals import PROPOSE_KINDS, TTL_SECONDS, clean_args, store


def run_propose(ctx: Ctx, run: Run) -> None:
    assert ctx.patient_id and ctx.ports is not None
    if ctx.session.role != "DOCTOR":
        run_refuse(ctx, run, "needs_doctor")
        return
    kind = ctx.step.params.get("kind")
    args = clean_args(ctx.step.params.get("args") or {}, ctx.question)
    if kind not in PROPOSE_KINDS or args is None:
        run_refuse(ctx, run, "needs_clarification")
        return
    with run.step("Preparing the change for your approval") as step:
        try:
            preview = ctx.ports.preview_proposal(
                ctx.session, kind, ctx.patient_id, args, ctx.last_answer_id
            )
        except ProposalInvalid as exc:
            step.detail = "needs more detail"
            run_refuse(ctx, run, "needs_clarification", str(exc))
            return
        proposal = store.add(
            ctx.session.user_id,
            ctx.patient_id,
            kind,
            preview.args,
            preview.title,
            preview.fields,
            ctx.question,
        )
        step.detail = f"{kind}, not saved"
    run.emit(
        "proposal",
        {
            "proposal_id": proposal.proposal_id,
            "kind": kind,
            "patient_id": ctx.patient_id,
            "title": preview.title,
            "fields": [{"label": a, "value": b} for a, b in preview.fields],
            "expires_in_seconds": TTL_SECONDS,
        },
    )
    run.audit_id = write_audit(
        ctx.session,
        AuditEntry(
            action="ASK", route="propose", model=ctx.info.model, confidence=ctx.info.confidence,
            cost_note="nothing saved until approved", patient_id=ctx.patient_id, question=ctx.question,
            steps=run.steps, outcome="OK", outcome_detail=f"{kind} {proposal.proposal_id}",
        ),
    )  # fmt: skip
