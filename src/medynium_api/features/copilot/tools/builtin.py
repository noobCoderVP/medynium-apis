"""The built-in read tools: the existing handlers, registered under stable names. Behaviour is unchanged."""

import dataclasses

from medynium_api.core.evidence.models import AnswerObject
from medynium_api.core.streaming import Run
from medynium_api.features.copilot.agent_plan import (
    AnalystArgs,
    ChangeArgs,
    LabArgs,
    LabelArgs,
    NoArgs,
    RecordArgs,
    ReportArgs,
)
from medynium_api.features.copilot.handlers import Ctx
from medynium_api.features.copilot.handlers.analyst import run_analyst
from medynium_api.features.copilot.handlers.intel import run_attention, run_changes_since, run_gaps
from medynium_api.features.copilot.handlers.knowledge import run_knowledge
from medynium_api.features.copilot.handlers.live_label import run_live_label
from medynium_api.features.copilot.handlers.lookup import run_changed, run_lookup
from medynium_api.features.copilot.handlers.report_reader import run_read_report
from medynium_api.features.copilot.panel import run_panel
from medynium_api.features.copilot.panel_plan import TOOLS as PANEL_TOOLS
from medynium_api.features.copilot.tools import Tool, register


def _with_question(ctx: Ctx, key: str) -> Ctx:
    """A tool called by the agent may carry its own sub-question; it is still just text for that tool."""
    sub = ctx.step.params.get(key)
    return dataclasses.replace(ctx, question=sub) if isinstance(sub, str) and sub.strip() else ctx


def _labels(ctx: Ctx, run: Run) -> AnswerObject:
    return run_knowledge(_with_question(ctx, "query"), run)


def _analyst(ctx: Ctx, run: Run) -> AnswerObject:
    return run_analyst(_with_question(ctx, "question"), run)


def _changes(ctx: Ctx, run: Run) -> AnswerObject:
    """Since the previous visit: the fixed, ground-truth query. A longer window uses the shared change rules."""
    return run_changes_since(ctx, run) if ctx.step.params.get("since") else run_changed(ctx, run)


def _record(ctx: Ctx, run: Run) -> AnswerObject:
    return run_lookup(ctx, run, ctx.step.params.get("kind") or "SUMMARY")


def _safety(ctx: Ctx, run: Run) -> AnswerObject:
    assert ctx.safety is not None and ctx.patient_id
    return ctx.safety.run(ctx.session, ctx.patient_id, run, question=ctx.question, route=ctx.info)


register(Tool("get_patient_record", "patient", "Read the open patient's active medicines, latest labs, utilisation or a summary, as plain SQL on the read models.", RecordArgs, _record, True))  # fmt: skip
register(Tool("detect_changes", "change", "What changed for the open patient since the previous visit; args.since 90d or 1y compares over a longer window instead.", ChangeArgs, _changes, True))  # fmt: skip
register(Tool("query_structured", "query", "Cortex Analyst: exact values, counts, filters and date comparisons for the open patient, run as the caller. Optional args.question is a narrower sub-question.", AnalystArgs, _analyst, True))  # fmt: skip
register(Tool("get_attention", "change", "What deserves attention for the open patient by fixed rules: abnormal or moving results, new medicines or diagnoses, emergency visit, findings and reports waiting.", NoArgs, run_attention, True))  # fmt: skip
register(Tool("get_gaps", "change", "What is missing for the open patient by fixed rules: usual follow-up results not seen lately, medicines with no indexed label, no allergy information.", NoArgs, run_gaps, True))  # fmt: skip
register(Tool("read_report", "patient", "What an uploaded report says: the best-matching pages of one report (args.report a file name, default the latest; args.query what to look for) as cited page excerpts.", ReportArgs, run_read_report, True))  # fmt: skip
register(Tool("lookup_label_live", "knowledge", "The current drug label straight from openFDA for a drug the indexed snapshot does not hold; only when asked by name (args.drug).", LabArgs, run_live_label, False))  # fmt: skip
register(Tool("run_safety_review", "safety", "Evidence-backed safety review of the open patient's medicines against labels, labs and allergies.", NoArgs, _safety, True, uses_model=True))  # fmt: skip
register(Tool("search_labels", "knowledge", "Search the indexed drug labels and return cited sections. Optional args.query is the drug and topic to search.", LabelArgs, _labels, False))  # fmt: skip
for _name in PANEL_TOOLS:
    register(Tool(_name, "panel", f"Panel tool {_name}: a read over the caller's own patients (see panel_plan).", NoArgs, run_panel, False))  # fmt: skip
