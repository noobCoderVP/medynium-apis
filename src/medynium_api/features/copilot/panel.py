"""panel: questions about the clinician's own patients as a group ("who are my patients", "what is pending", "what
changed since Monday", "my diabetics with eGFR under 60"). Production plan Phase 3.

Four read-only tools, each plain SQL over the read models under the caller's own role, so the entitled-patient policy
bounds every result. No model writes the answer: each row becomes one statement with its evidence, the validator
below checks every patient against the caller's entitlement list, and counts come from the rows themselves. These are
tools, not actions: the closed action set (open a patient, show a timeline, run the review, pin evidence) is unchanged,
and nothing here can change the record."""

import datetime as dt
import json
from typing import Any

import structlog

from medynium_api.core.access import entitled_patients
from medynium_api.core.evidence.models import (
    AnswerObject,
    Consideration,
    EvidenceBundle,
    Limits,
    PatientEvidence,
)
from medynium_api.core.schemas import flags_from
from medynium_api.core.snowflake.queries import Row, json_value
from medynium_api.core.streaming import Run
from medynium_api.features.copilot.answers import finalize
from medynium_api.features.copilot.handlers import Ctx
from medynium_api.features.copilot.panel_plan import (
    SECTION,
    since_from,
    validate_calls,
    wants_detail,
)
from medynium_api.features.copilot.panel_repository import (
    LIMIT,
    PanelFilters,
    PanelQueries,
)
from medynium_api.features.copilot.panel_similar import run_similar
from medynium_api.features.copilot.panel_summary import (
    PLAN_RECORD,
    group_pending,
    matching_summary,
    patients_summary,
    pending_summary,
)

log = structlog.get_logger()


# Rows to statements ----------------------------------------------------------------------------------------------
def _patient_text(r: Row) -> str:
    diagnoses = json_value(r["main_diagnoses"]) or []
    flags = flags_from(
        int(r["new_lab_count"] or 0), bool(r["has_new_medication_change"]), bool(r["has_recent_emergency"]),
        bool(r["has_new_document"]), r["last_encounter_date"],
    )  # fmt: skip
    head = f"{r['full_name']}, {r['age_years']} {r['sex']}"
    if diagnoses:
        head += ": " + ", ".join(str(d) for d in diagnoses[:2])
    extra = []
    if r.get("lab_value") is not None:
        extra.append(f"{r['lab_test']} {float(r['lab_value']):g} {r['lab_unit'] or ''}".strip())
    if r.get("med_drug"):
        extra.append(f"on {r['med_drug']}")
    tail = [*extra, *(f.label for f in flags)]
    return head + ("; " + "; ".join(tail) if tail else "")


class Builder:
    """Collects statements and their evidence with ids that stay unique across the tools of one answer."""

    def __init__(self, entitled: frozenset[str]) -> None:
        self.entitled = entitled
        self.items: list[PatientEvidence] = []
        self.considerations: list[Consideration] = []
        self.outside = 0

    def add(
        self, group: str, patient_id: str, text: str, record_type: str, record_id: str | None, table: str,
        date: dt.date | None, *, quiet: bool = False,
    ) -> None:  # fmt: skip
        """`quiet` keeps the evidence (the Why? panel still opens it) but shows no statement line in the answer."""
        if (
            patient_id not in self.entitled
        ):  # the policy already filters; this is the second, independent check
            self.outside += 1
            return
        n = len(self.items) + 1
        self.items.append(
            PatientEvidence(evidence_id=f"P{n}", record_type=record_type, record_id=record_id, table=table, value=text, date=date)
        )  # fmt: skip
        if quiet:
            return
        self.considerations.append(
            Consideration(id=f"C{len(self.considerations) + 1}", text=text, tag="patient_fact", patient_evidence=[f"P{n}"], patient_id=patient_id, group=group)
        )  # fmt: skip


def _titled(event_type: str) -> str:
    return event_type.replace("_", " ").title()


def run_panel(ctx: Ctx, run: Run) -> AnswerObject | None:
    calls = validate_calls(ctx.step.params)
    if calls is None:
        return None
    role = ctx.session.snowflake_role
    queries = PanelQueries()
    recorded: list[Any] = []
    builder = Builder(entitled_patients(ctx.session.user_id))
    as_of = dt.date.fromisoformat(ctx.settings.as_of_iso)
    sentences: list[str] = []
    checked: list[str] = []
    notes: list[str] = []
    want_detail = wants_detail(
        ctx.question
    )  # patient-by-patient lines only when the clinician asks for them
    for call in calls:
        group = SECTION[call.tool]
        with run.step(f"Reading {group.lower()}") as step:
            if call.tool in ("list_my_patients", "patients_matching"):
                filters = call.filters if call.tool == "patients_matching" else PanelFilters()
                rows = queries.patients(role, filters, recorded)
                total = int(rows[0]["total"]) if rows else 0
                for r in rows:
                    builder.add(group, r["patient_id"], _patient_text(r), "Patient", r["patient_id"], "ANALYTICS.DASHBOARD_WORKLIST", r["last_encounter_date"], quiet=not want_detail)  # fmt: skip
                    if r.get("lab_id"):  # the matching result is its own record
                        builder.add(group, r["patient_id"], f"{r['full_name']}: {r['lab_test']} {float(r['lab_value']):g} {r['lab_unit'] or ''}".strip(), "Lab result", r["lab_id"], "CLINICAL.LAB_RESULT", None, quiet=not want_detail)  # fmt: skip
                checked.append("ANALYTICS.DASHBOARD_WORKLIST and the patient read models")
                if call.tool == "list_my_patients":
                    counts = queries.patient_counts(role, recorded)
                    sentences.append(patients_summary(counts, rows, total, want_detail))
                else:
                    sentences.append(matching_summary(total, call.filters.describe(), rows, LIMIT, want_detail))  # fmt: skip
            elif call.tool == "similar_patients":
                pid = call.patient_id or ctx.patient_id
                if not pid:
                    return None  # nothing open to compare: ask the clinician to name the patient
                if not run_similar(
                    role,
                    pid,
                    ctx.settings.similar_weight_embedding,
                    builder.add,
                    group,
                    recorded,
                    sentences,
                    notes,
                ):
                    raise LookupError("patient not visible")
                checked.append(
                    "ANALYTICS.PATIENT_EMBEDDING (vector similarity) and the patient read models"
                )
                total = len(builder.items)
            elif call.tool == "pending_work":
                rows = queries.pending(role, call.kinds, call.patient_id, recorded)
                total = int(rows[0]["total"]) if rows else 0
                overdue = sum(
                    1
                    for r in rows
                    if r["kind"] == "FOLLOW_UP" and r["due_date"] and r["due_date"] <= as_of
                )
                for g in group_pending(rows):  # one line per patient, not one per lab value
                    first = g["first"]
                    one = (
                        not g["many"] and want_detail
                    )  # a quiet answer keeps the patient, so a follow-up can open them
                    kind = {"ABNORMAL_LAB": "Lab result", "RECENT_EMERGENCY": "Visit", "REPORT_TO_REVIEW": "Report"}.get(first["kind"], "Finding") if one else "Patient"  # fmt: skip
                    raised = first["raised_at"].date() if first["raised_at"] else None
                    builder.add(group, g["patient_id"], g["text"], kind, first["source_id"] if one else g["patient_id"], first["source_table"] if one else "ANALYTICS.PENDING_ITEM", raised, quiet=not want_detail)  # fmt: skip
                checked.append("ANALYTICS.PENDING_ITEM (findings, abnormal labs, emergency visits)")
                counts_by_kind = queries.pending_counts(role, call.kinds, call.patient_id, recorded)
                sentences.append(pending_summary(counts_by_kind, total, overdue, rows, want_detail))
            else:
                since = call.since or since_from(ctx.question, as_of)
                rows = queries.changes(role, since, as_of, recorded)
                total = int(rows[0]["total"]) if rows else 0
                for r in rows:
                    detail = f": {r['summary']}" if r["summary"] else ""
                    builder.add(group, r["patient_id"], f"{r['full_name']}, {r['event_date']:%d %b}: {r['title']}{detail}", _titled(r["event_type"]), r["record_id"], r["record_table"] or "", r["event_date"], quiet=not want_detail)  # fmt: skip
                checked.append("ANALYTICS.PATIENT_TIMELINE (claims left out)")
                sentences.append(
                    f"{total} change{'s' if total != 1 else ''} across your patients since {since:%d %b}"
                    + (
                        "."
                        if total <= LIMIT or not want_detail
                        else f"; the {LIMIT} most recent are listed."
                    )
                    + ("" if want_detail or not rows else " Ask me to list them for the detail.")
                )
            step.detail = f"{total} found"
    if not any(
        c.tool == "similar_patients" for c in calls
    ):  # remembered, so "list them" can repeat the same read
        plan = json.dumps([c.model_dump(mode="json", exclude_defaults=True) for c in calls])
        builder.items.append(PatientEvidence(evidence_id=f"P{len(builder.items) + 1}", record_type=PLAN_RECORD, record_id=None, table="", value=plan, date=None))  # fmt: skip
    if builder.outside:
        log.error("panel_row_outside_entitlement", dropped=builder.outside)
        notes.append(f"{builder.outside} row(s) outside your entitlement were removed.")
    notes.append(
        "Plain SQL over your own patients; no model wrote this answer. The summary is counted from the rows; Why? opens the records and the SQL behind it."
    )
    ctx.info.cost_note = "no model call"
    return finalize(
        ctx.session, run, kind="PANEL", patient_id=None, short_answer=" ".join(sentences),
        considerations=builder.considerations, limits=Limits(checked=checked, notes=notes, snapshot_date=as_of),
        conflicts=[], bundle=EvidenceBundle(patient_records=builder.items, sql=recorded), route=ctx.info,
        question=ctx.question, action="ASK",
    )  # fmt: skip
