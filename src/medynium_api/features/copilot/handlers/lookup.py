"""lookup (and the deterministic "what changed" path): plain SQL on the read models, no model call (FR-05, NFR-03)."""

import datetime as dt
import re

from medynium_api.core.evidence.models import (
    AnswerObject,
    Consideration,
    EvidenceBundle,
    Kind,
    Limits,
    PatientEvidence,
    SqlEvidence,
)
from medynium_api.core.streaming import Run
from medynium_api.features.copilot.answers import finalize
from medynium_api.features.copilot.handlers import Ctx
from medynium_api.features.copilot.pack import num, patient_evidence, when
from medynium_api.features.copilot.repository import Facts

CHANGED = re.compile(
    r"\bchang(e|ed|es)\b|what'?s new|since (the |my )?(last|previous|prior) (visit|appointment)",
    re.IGNORECASE,
)
KINDS: list[tuple[Kind, re.Pattern[str]]] = [
    ("MEDS", re.compile(r"\b(medication|medicine|drug|taking|prescri|tablet)", re.IGNORECASE)),
    (
        "LABS",
        re.compile(
            r"\b(lab|egfr|creatinine|hba1c|potassium|sodium|haemoglobin|hemoglobin|tsh|ldl|glucose|result|test)",
            re.IGNORECASE,
        ),
    ),
    (
        "UTIL",
        re.compile(
            r"\b(visit|claim|cost|utili[sz]ation|admission|admitted|hospital|bill|insurance|approved|procedure)",
            re.IGNORECASE,
        ),
    ),
    ("SUMMARY", re.compile(r"\b(summary|summari[sz]e|overview|snapshot)\b", re.IGNORECASE)),
]
NO_MODEL = "no model call"


def classify(question: str) -> Kind | None:
    if CHANGED.search(question):
        return "CHANGED"
    return next((kind for kind, pattern in KINDS if pattern.search(question)), None)


def _statements(
    items: list[PatientEvidence], kinds: dict[str, str], wanted: set[str]
) -> list[Consideration]:
    picked = [p for p in items if kinds.get(p.evidence_id) in wanted]
    return [Consideration(id=f"C{i}", text=p.value.split(": ", 1)[0] if p.record_type == "Note" else p.value, tag="patient_fact", patient_evidence=[p.evidence_id]) for i, p in enumerate(picked, start=1)]  # fmt: skip


def _limits(ctx: Ctx, checked: str) -> Limits:
    return Limits(
        checked=[checked],
        notes=["No AI call was needed: this is a plain SQL read of the precomputed record."],
        snapshot_date=dt.date.fromisoformat(ctx.settings.as_of_iso),
    )


def run_lookup(ctx: Ctx, run: Run, kind: Kind) -> AnswerObject:
    assert ctx.patient_id
    session = ctx.session
    with run.step(
        f"Reading the {kind.lower() if kind != 'UTIL' else 'utilisation'} record"
    ) as step:
        facts: Facts | None = ctx.repo.patient_facts(session.snowflake_role, ctx.patient_id)
        if facts is None:
            raise LookupError("patient not visible")
        items, _, kinds = patient_evidence(facts)
        recorded = list(facts.sql)
        step.detail = "plain SQL"
        if kind == "UTIL":
            row = ctx.queries.utilization(session.snowflake_role, ctx.patient_id, recorded)
            if row:
                n = len(items) + 1
                value = (
                    f"{row['opd_visits']} outpatient visits, {row['emergency_visits']} emergency visits, "
                    f"{row['hospitalizations']} hospital stays, {row['procedures']} procedures; billed ₹{row['billed_inr']:,.0f}, "
                    f"approved ₹{row['approved_inr']:,.0f} in the last 12 months"
                )
                items.append(PatientEvidence(evidence_id=f"P{n}", record_type="Utilization", record_id=None, table="ANALYTICS.UTILIZATION", value=value))  # fmt: skip
                kinds[f"P{n}"] = "utilization"

    wanted = {"MEDS": {"medication"}, "LABS": {"abnormal_lab", "lab"}, "UTIL": {"utilization"}, "SUMMARY": {"medication", "abnormal_lab", "lab", "diagnosis"}}[kind]  # fmt: skip
    considerations = _statements(items, kinds, wanted)
    noun = {
        "MEDS": "active medicines",
        "LABS": "latest laboratory results",
        "UTIL": "utilisation figures",
        "SUMMARY": "record items",
    }[kind]
    short = (
        f"{facts.name} has {len(considerations)} {noun} on record."
        if considerations
        else f"No {noun} are on record for {facts.name}."
    )
    checked = {"MEDS": "CLINICAL.MEDICATION, active", "LABS": "CLINICAL.LAB_RESULT, latest per test", "UTIL": "ANALYTICS.UTILIZATION and CLINICAL.CLAIM", "SUMMARY": "ANALYTICS.PATIENT_360 and its read models"}[kind]  # fmt: skip
    ctx.info.cost_note = NO_MODEL
    return finalize(
        session, run, kind=kind, patient_id=ctx.patient_id, short_answer=short, considerations=considerations,
        limits=_limits(ctx, checked), conflicts=[], bundle=EvidenceBundle(patient_records=items, sql=recorded),
        route=ctx.info, question=ctx.question, action="ASK",
    )  # fmt: skip


def run_changed(ctx: Ctx, run: Run) -> AnswerObject:
    """What changed since the previous visit: a fixed query, so the answer equals the ground-truth SQL (HJ-2)."""
    assert ctx.patient_id
    recorded: list[SqlEvidence] = []
    with run.step("Comparing with the previous visit") as step:
        head, rows = ctx.queries.changed_since_last_visit(
            ctx.session.snowflake_role, ctx.patient_id, recorded
        )
        if head is None:
            raise LookupError("patient not visible")
        step.detail = f"{len(rows)} events since {when(head['previous_encounter_date'])}"
    items = [
        PatientEvidence(
            evidence_id=f"P{i}",
            record_type=r["event_type"].title().replace("_", " "),
            record_id=r["record_id"],
            table=r["record_table"] or "",
            value=r["title"]
            if r["event_type"] == "NOTE" or not r["summary"]
            else f"{r['title']}: {r['summary']}",
            date=r["event_date"],
        )
        for i, r in enumerate(rows, start=1)
    ]
    considerations = [Consideration(id=f"C{i}", text=f"{when(p.date)}: {p.value}", tag="patient_fact", patient_evidence=[p.evidence_id]) for i, p in enumerate(items, start=1)]  # fmt: skip
    since = when(head["previous_encounter_date"])
    short = (
        f"{len(rows)} changes since the previous visit on {since}."
        if rows
        else f"No new events since the previous visit on {since}."
    )
    ctx.info.cost_note = NO_MODEL
    return finalize(
        ctx.session, run, kind="CHANGED", patient_id=ctx.patient_id, short_answer=short, considerations=considerations,
        limits=_limits(ctx, "ANALYTICS.PATIENT_TIMELINE after the previous visit"), conflicts=[],
        bundle=EvidenceBundle(patient_records=items, sql=recorded), route=ctx.info, question=ctx.question, action="ASK",
    )  # fmt: skip


__all__ = ["classify", "num", "run_changed", "run_lookup"]
