"""attention, gaps and longer-range changes as assistant tools: the same rules the Brief screen uses (core/intel), so a
person and the assistant see the same items. Plain SQL and fixed rules, no model call. Every item becomes a record
with its source, so the Why? panel can open the lab, medicine or report it came from."""

import datetime as dt
from collections.abc import Sequence

from medynium_api.core.evidence.models import (
    AnswerObject,
    Consideration,
    EvidenceBundle,
    Limits,
    PatientEvidence,
    Tag,
)
from medynium_api.core.intel import data
from medynium_api.core.intel.models import TABLE, AttentionItem, ChangeItem, GapItem, SourceRef
from medynium_api.core.streaming import Run
from medynium_api.features.copilot.answers import finalize
from medynium_api.features.copilot.handlers import Ctx

RULE_TABLE = "ANALYTICS (fixed rule)"


def _evidence(rows: Sequence[tuple[str, str | None, SourceRef | None, dt.date | None]], tag: Tag) -> tuple[list[PatientEvidence], list[Consideration]]:  # fmt: skip
    items: list[PatientEvidence] = []
    statements: list[Consideration] = []
    for text, _, source, date in rows:
        n = len(items) + 1
        table = TABLE[source.type] if source else RULE_TABLE
        kind = source.type.title() if source else "Rule"
        items.append(PatientEvidence(evidence_id=f"P{n}", record_type=kind, record_id=source.id if source else None, table=table, value=text, date=date))  # fmt: skip
        statements.append(Consideration(id=f"C{n}", text=text, tag=tag, patient_evidence=[f"P{n}"]))
    return items, statements


def _text(title: str, detail: str | None) -> str:
    return f"{title}. {detail}" if detail else title


def _limits(ctx: Ctx, checked: str, notes: list[str]) -> Limits:
    return Limits(
        checked=[checked], notes=notes, snapshot_date=dt.date.fromisoformat(ctx.settings.as_of_iso)
    )


def _finish(ctx: Ctx, run: Run, short: str, items: list[PatientEvidence], statements: list[Consideration], limits: Limits) -> AnswerObject:  # fmt: skip
    ctx.info.cost_note = "no model call"
    return finalize(
        ctx.session, run, kind="SUMMARY", patient_id=ctx.patient_id, short_answer=short, considerations=statements,
        limits=limits, conflicts=[], bundle=EvidenceBundle(patient_records=items), route=ctx.info,
        question=ctx.question, action="ASK",
    )  # fmt: skip


def run_attention(ctx: Ctx, run: Run) -> AnswerObject:
    assert ctx.patient_id
    with run.step("Applying the attention rules") as step:
        found: list[AttentionItem] | None = data.attention_items(
            ctx.session.snowflake_role, ctx.patient_id
        )
        if found is None:
            raise LookupError("patient not visible")
        step.detail = f"{len(found)} items"
    rows = [(_text(i.title, i.detail), None, i.source, i.date) for i in found]
    items, statements = _evidence(rows, "patient_fact")
    short = (
        f"{len(found)} item{'s' if len(found) != 1 else ''} may need attention."
        if found
        else "Nothing stands out for attention by the fixed rules."
    )
    notes = ["Fixed rules over the record: abnormal or moving results, new medicines or diagnoses, an emergency visit, findings and reports waiting."]  # fmt: skip
    return _finish(ctx, run, short, items, statements, _limits(ctx, "ANALYTICS.PATIENT_LAB_LATEST, PATIENT_TIMELINE and PENDING_ITEM", notes))  # fmt: skip


def run_gaps(ctx: Ctx, run: Run) -> AnswerObject:
    assert ctx.patient_id
    with run.step("Looking for missing information") as step:
        found: list[GapItem] | None = data.gap_items(ctx.session.snowflake_role, ctx.patient_id)
        if found is None:
            raise LookupError("patient not visible")
        step.detail = f"{len(found)} gaps"
    rows = [(_text(g.title, g.detail), None, g.source, None) for g in found]
    items, statements = _evidence(rows, "rule_check")
    short = (
        f"{len(found)} possible gap{'s' if len(found) != 1 else ''} in the record."
        if found
        else "The fixed rules found no gaps. This is not a statement that nothing is missing."
    )
    notes = ["Usual follow-up checks (for example HbA1c on metformin) and missing information. They are prompts to look, not requirements."]  # fmt: skip
    return _finish(ctx, run, short, items, statements, _limits(ctx, "Active medicines, diagnoses and the latest result per test", notes))  # fmt: skip


def run_changes_since(ctx: Ctx, run: Run) -> AnswerObject:
    """Changes over a longer window ("last 90 days", "last year"); the previous-visit comparison has its own fixed query."""
    assert ctx.patient_id
    choice = str(ctx.step.params.get("since") or "90d")
    with run.step("Comparing with the earlier record") as step:
        result = data.change_set(ctx.session.snowflake_role, ctx.patient_id, choice)
        if result is None:
            raise LookupError("patient not visible")
        step.detail = f"{len(result.items)} changes {result.label}"
    changes: list[ChangeItem] = result.items[:25]
    rows = [(f"{c.date:%d %b %Y}: " + _text(c.title, c.detail) if c.date else _text(c.title, c.detail), None, c.source, c.date) for c in changes]  # fmt: skip
    items, statements = _evidence(rows, "patient_fact")
    short = f"{len(result.items)} change{'s' if len(result.items) != 1 else ''} {result.label}."
    notes = ["Lab results are compared with the previous result for the same test. Claims are not counted as clinical changes."]  # fmt: skip
    return _finish(ctx, run, short, items, statements, _limits(ctx, "ANALYTICS.PATIENT_TIMELINE, PATIENT_LAB_LATEST and reports", notes))  # fmt: skip
