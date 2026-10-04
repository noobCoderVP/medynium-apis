"""lookup_label_live: a cited look at a drug label straight from openFDA, for a drug the indexed snapshot does not hold.
Only on request by name. The text is shown as a retrieved source marked live, never mixed into the stored snapshot, and
never read as instructions. A failed lookup is an honest gap, not a guess."""

import datetime as dt

from medynium_api.core import openfda
from medynium_api.core.evidence.models import (
    AnswerObject,
    Consideration,
    EvidenceBundle,
    Limits,
    SourceEvidence,
)
from medynium_api.core.streaming import Run
from medynium_api.features.copilot.answers import finalize
from medynium_api.features.copilot.handlers import Ctx

SOURCE = "openFDA live API"


def run_live_label(ctx: Ctx, run: Run) -> AnswerObject:
    drug = str(ctx.step.params.get("drug") or "").strip()
    today = dt.date.fromisoformat(ctx.settings.as_of_iso)
    with run.step("Asking openFDA for the current label") as step:
        found = openfda.fetch_label(drug) if drug else None
        step.detail = "unavailable" if found is None else f"{len(found)} sections"
    sources: list[SourceEvidence] = []
    for i, s in enumerate(found or [], start=1):
        effective = None
        if s.effective and len(s.effective) == 8 and s.effective.isdigit():
            effective = dt.date(int(s.effective[:4]), int(s.effective[4:6]), int(s.effective[6:]))
        sources.append(SourceEvidence(evidence_id=f"S{i}", chunk_id=f"openfda:{s.document_id}:{i}", document_id=s.document_id, title=s.title, source=SOURCE, section=s.section, version=s.version, effective_date=effective, retrieved_date=today, text=s.text))  # fmt: skip
    statements = [
        Consideration(
            id=f"C{i}",
            text=(s.text[:320].rsplit(" ", 1)[0] + "...") if len(s.text) > 320 else s.text,
            tag="retrieved_source",
            source_evidence=[s.evidence_id],
        )
        for i, s in enumerate(sources, start=1)
    ]
    if found is None:
        short, checked, not_checked = "openFDA could not be reached, or that is not a plain drug name.", [], [f"{drug or 'the drug'}: the live lookup failed"]  # fmt: skip
    elif not sources:
        short, checked, not_checked = f"openFDA has no label for {drug}.", [f"openFDA live lookup for {drug}"], []  # fmt: skip
    else:
        short, checked, not_checked = f"{len(sources)} section{'s' if len(sources) != 1 else ''} from the current openFDA label for {drug}.", [f"openFDA live lookup for {drug}"], []  # fmt: skip
    ctx.info.cost_note = "no model call"
    notes = ["Fetched live from openFDA just now; it is not part of the stored snapshot and has not been reviewed.", "US FDA label text, not Indian regulatory text."]  # fmt: skip
    return finalize(
        ctx.session, run, kind="KNOWLEDGE", patient_id=None, short_answer=short, considerations=statements,
        limits=Limits(checked=checked, not_checked=not_checked, notes=notes, snapshot_date=today), conflicts=[],
        bundle=EvidenceBundle(sources=sources), route=ctx.info, question=ctx.question, action="ASK",
    )  # fmt: skip
