"""knowledge: label text found by Cortex Search, shown as cited sections. No generated text, no model call."""

import datetime as dt
import re

from medynium_api.core.cortex.models import Retrieval
from medynium_api.core.cortex.search_client import flag_conflicts
from medynium_api.core.evidence.models import (
    AnswerObject,
    ConflictItem,
    Consideration,
    EvidenceBundle,
    Limits,
)
from medynium_api.core.streaming import Run
from medynium_api.features.copilot.answers import finalize
from medynium_api.features.copilot.handlers import Ctx
from medynium_api.features.copilot.pack import focus_terms, sources

NOT_FOUND = "Not found in the indexed sources."


def run_knowledge(ctx: Ctx, run: Run) -> AnswerObject:
    role = ctx.session.snowflake_role
    with run.step("Searching the indexed labels") as step:
        words = re.findall(r"[a-z0-9][a-z0-9-]*", ctx.question.lower())
        matches = ctx.queries.resolve_names(role, list(set(words)))
        drug_ids = sorted({m["drug_id"] for m in matches})
        brands = {m["name_text"] for m in matches if m["name_kind"] == "INDIAN_BRAND"}
        query = " ".join(
            [*(w for w in words if w not in brands), *sorted({m["display_name"] for m in matches})]
        )
        if not drug_ids and ctx.patient_id and ctx.step.route == "agent":
            # The question names no drug but a patient is open: look at the labels of the medicines they take.
            facts = ctx.repo.patient_facts(ctx.session.snowflake_role, ctx.patient_id)
            if facts is None:
                raise LookupError("patient not visible")
            drugs = {m["drug_id"]: m["drug_name"] for m in facts.meds if m["drug_id"]}
            chunks = (
                ctx.search.retrieve_for_patient(
                    drugs, focus_terms(facts), per_drug=1, total=4
                ).chunks
                if drugs
                else []
            )
        else:
            chunks = ctx.search.search(query, drug_ids=drug_ids or None, limit=4)
        step.detail = f"{len(chunks)} sections"
    flag_conflicts(chunks)
    retrieval = Retrieval(chunks=chunks, checked_nothing=[], conflicts=flag_conflicts(chunks))
    bundle = EvidenceBundle(sources=sources(retrieval))
    considerations = [
        Consideration(id=f"C{i}", text=(s.text[:320].rsplit(" ", 1)[0] + "...") if len(s.text) > 320 else s.text, tag="retrieved_source", source_evidence=[s.evidence_id])
        for i, s in enumerate(bundle.sources, start=1)
    ]  # fmt: skip
    conflicts = [ConflictItem(drug=g.drug_name, section=g.section, items=[s.evidence_id for s in bundle.sources if s.chunk_id in g.chunk_ids]) for g in retrieval.conflicts]  # fmt: skip
    short = (
        f"{len(chunks)} matching section{'s' if len(chunks) != 1 else ''} in the indexed sources."
        if chunks
        else NOT_FOUND
    )
    ctx.info.cost_note = "no model call"
    return finalize(
        ctx.session,
        run,
        kind="KNOWLEDGE",
        patient_id=None,
        short_answer=short,
        considerations=considerations,
        limits=Limits(
            checked=["Cortex Search over the label snapshot"],
            notes=["US FDA label text. The corpus is a snapshot, not a live feed."],
            snapshot_date=dt.date.fromisoformat(ctx.settings.as_of_iso),
        ),
        conflicts=conflicts,
        bundle=bundle,
        route=ctx.info,
        question=ctx.question,
        action="ASK",
    )
