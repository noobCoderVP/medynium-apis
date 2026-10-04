"""read_report: what an uploaded report says, page by page, for the open patient (agentic upgrade, phase F).

The pages were parsed when the report was uploaded and are stored with it. This tool picks the report (by name or the
latest), ranks its pages against the question by plain word overlap, and returns the best pages as cited excerpts. The
page text is data copied from a document: it is shown as a quote with its page number and is never read as instructions
(the composer wraps it as untrusted). Plain SQL under the caller's role; no model call here."""

import datetime as dt
import re
from typing import Any

from medynium_api.core.evidence.models import (
    AnswerObject,
    Consideration,
    EvidenceBundle,
    Limits,
    PatientEvidence,
)
from medynium_api.core.snowflake.queries import fetch_all
from medynium_api.core.snowflake.role_session import user_cursor
from medynium_api.core.streaming import Run
from medynium_api.features.copilot.answers import finalize
from medynium_api.features.copilot.handlers import Ctx

MAX_PAGES = 3
EXCERPT = 1200
WORD = re.compile(r"[a-z0-9]{4,}")
STOP = {"report", "what", "does", "this", "that", "with", "from", "about", "page", "pages", "summarize", "summary", "tell"}  # fmt: skip


def rank(pages: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Pages with the most of the question's words first; with no useful words, the first pages in order."""
    words = {w for w in WORD.findall(query.lower()) if w not in STOP}
    if not words:
        return pages[:MAX_PAGES]
    scored = sorted(
        pages, key=lambda p: (-sum(1 for w in words if w in p["page_text"].lower()), p["page_no"])
    )
    best = [p for p in scored if any(w in p["page_text"].lower() for w in words)][:MAX_PAGES]
    return sorted(best or pages[:MAX_PAGES], key=lambda p: p["page_no"])


def pick(reports: list[dict[str, Any]], wanted: str | None) -> dict[str, Any] | None:
    if not reports:
        return None
    if wanted:
        needle = wanted.lower()
        for r in reports:
            if needle in str(r["filename"]).lower() or needle == str(r["report_id"]).lower():
                return r
    return reports[0]


def run_read_report(ctx: Ctx, run: Run) -> AnswerObject:
    assert ctx.patient_id
    role, pid = ctx.session.snowflake_role, ctx.patient_id
    wanted = ctx.step.params.get("report")
    query = str(ctx.step.params.get("query") or ctx.question)
    with run.step("Finding the report") as step:
        with user_cursor(role) as cur:
            reports = fetch_all(
                cur,
                "SELECT REPORT_ID, FILENAME, STATUS, PAGE_COUNT, EXTRACTED_AT FROM CLINICAL.REPORT WHERE PATIENT_ID = %s "
                "AND STATUS IN ('EXTRACTED', 'REVIEWED') ORDER BY EXTRACTED_AT DESC LIMIT 10",
                (pid,),
            )  # fmt: skip
        chosen = pick(reports, wanted if isinstance(wanted, str) else None)
        step.detail = chosen["filename"] if chosen else "no report"
    today = dt.date.fromisoformat(ctx.settings.as_of_iso)
    ctx.info.cost_note = "no model call"
    if chosen is None:
        return finalize(
            ctx.session, run, kind="SUMMARY", patient_id=pid, short_answer="There is no read report on this patient.",
            considerations=[], limits=Limits(checked=["CLINICAL.REPORT for this patient"], notes=["Upload a report on the Reports tab first."], snapshot_date=today),
            conflicts=[], bundle=EvidenceBundle(), route=ctx.info, question=ctx.question, action="ASK",
        )  # fmt: skip
    with run.step("Reading its pages") as step:
        with user_cursor(role) as cur:
            pages = fetch_all(cur, "SELECT PAGE_NO, PAGE_TEXT FROM CLINICAL.REPORT_PAGE WHERE REPORT_ID = %s AND PATIENT_ID = %s ORDER BY PAGE_NO", (chosen["report_id"], pid))  # fmt: skip
        best = rank(pages, query)
        step.detail = f"{len(best)} of {len(pages)} pages"
    items: list[PatientEvidence] = []
    statements: list[Consideration] = []
    for p in best:
        text = " ".join(str(p["page_text"]).split())
        n = len(items) + 1
        value = f"{chosen['filename']}, page {p['page_no']}: {text[:EXCERPT]}"
        items.append(PatientEvidence(evidence_id=f"P{n}", record_type="Report page", record_id=chosen["report_id"], table="CLINICAL.REPORT", value=value, date=chosen["extracted_at"].date() if chosen.get("extracted_at") else None))  # fmt: skip
        shown = text[:300].rsplit(" ", 1)[0] + "..." if len(text) > 300 else text
        statements.append(Consideration(id=f"C{n}", text=f"{chosen['filename']}, page {p['page_no']}: {shown}", tag="patient_fact", patient_evidence=[f"P{n}"]))  # fmt: skip
    short = f"{len(best)} page{'s' if len(best) != 1 else ''} of {chosen['filename']} ({len(pages)} in all) read for this question."
    limits = Limits(
        checked=[f"{chosen['filename']}: pages {', '.join(str(p['page_no']) for p in best)} of {len(pages)}"],
        not_checked=[f"{r['filename']}: another report on this patient" for r in reports if r["report_id"] != chosen["report_id"]][:3],
        notes=["Quoted from the uploaded report, which is data and not instructions. Values are only in the record once a doctor approves them."],
        snapshot_date=today,
    )  # fmt: skip
    return finalize(
        ctx.session, run, kind="SUMMARY", patient_id=pid, short_answer=short, considerations=statements, limits=limits,
        conflicts=[], bundle=EvidenceBundle(patient_records=items), route=ctx.info, question=ctx.question, action="ASK",
    )  # fmt: skip
