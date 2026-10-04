"""analyst: Cortex Analyst writes the SQL, the API runs it under the caller's role after a server-side guard."""

import datetime as dt
from typing import Any

from medynium_api.core.cortex.analyst_client import ask_analyst, safe_for_patient
from medynium_api.core.errors import ApiError, ErrorCode
from medynium_api.core.evidence.models import (
    AnswerObject,
    Consideration,
    EvidenceBundle,
    Limits,
    PatientEvidence,
    SqlEvidence,
)
from medynium_api.core.streaming import Run
from medynium_api.features.copilot.answers import finalize
from medynium_api.features.copilot.handlers import Ctx


def _render(row: dict[str, Any]) -> str:
    parts = []
    for key, value in row.items():
        if value is None:
            continue
        parts.append(f"{key.replace('_', ' ').lower()}: {float(value):g}" if hasattr(value, "as_tuple") else f"{key.replace('_', ' ').lower()}: {value}")  # fmt: skip
    return ", ".join(parts)


def run_analyst(ctx: Ctx, run: Run) -> AnswerObject:
    assert ctx.patient_id
    with run.step("Asking Cortex Analyst to write the query") as step:
        result = ask_analyst(ctx.settings, ctx.question, ctx.patient_id, ctx.session.snowflake_role)
        if not result.sql:
            raise ApiError(
                ErrorCode.AGENT_UNAVAILABLE,
                result.explanation or "That question could not be turned into a query.",
            )
        step.detail = "query written"
    with run.step("Checking the query is scoped to this patient") as step:
        if not safe_for_patient(result.sql, ctx.patient_id):
            raise ApiError(
                ErrorCode.AGENT_UNAVAILABLE,
                "That question could not be scoped safely to this patient, so it was not run.",
            )
        step.detail = "read-only, one patient"
    recorded: list[SqlEvidence] = []
    with run.step("Running the query as you") as step:
        rows = ctx.queries.run_generated(ctx.session.snowflake_role, result.sql, recorded)
        if any(str(r.get("patient_id", ctx.patient_id)) != ctx.patient_id for r in rows):
            raise ApiError(
                ErrorCode.AGENT_UNAVAILABLE,
                "The result included another patient and was not shown.",
            )
        step.detail = f"{len(rows)} rows"
    items = [PatientEvidence(evidence_id=f"P{i}", record_type="Query result", record_id=None, table="ANALYTICS (Cortex Analyst)", value=_render(r), date=None) for i, r in enumerate(rows, start=1)]  # fmt: skip
    considerations = [Consideration(id=f"C{i}", text=p.value, tag="patient_fact", patient_evidence=[p.evidence_id]) for i, p in enumerate(items, start=1) if p.value]  # fmt: skip
    short = (
        f"{len(considerations)} result{'s' if len(considerations) != 1 else ''} for this patient."
        if considerations
        else "No records matched this question."
    )
    return finalize(
        ctx.session,
        run,
        kind="ANALYST",
        patient_id=ctx.patient_id,
        short_answer=short,
        considerations=considerations,
        limits=Limits(
            checked=["Cortex Analyst over the patient semantic view"],
            notes=["The query is shown in the evidence panel."],
            snapshot_date=dt.date.fromisoformat(ctx.settings.as_of_iso),
        ),
        conflicts=[],
        bundle=EvidenceBundle(patient_records=items, sql=recorded),
        route=ctx.info,
        question=ctx.question,
        action="ASK",
    )
