"""The safety review (the hero flow). Evidence-pack path (ADR-015): a deterministic pass reads the patient's facts
under their own role, retrieval is filtered to the patient's drugs, ONE strong-model call drafts statements over
that pack, and the validator disposes of everything the evidence does not back."""

import json
import time
from typing import Any

import structlog

from medynium_api.core.access import log_policy_disagreement, require_patient
from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.config import Settings
from medynium_api.core.cortex.complete import Completion, complete
from medynium_api.core.cortex.models import Retrieval
from medynium_api.core.cortex.search_client import SearchClient
from medynium_api.core.errors import ApiError, ErrorCode, not_found
from medynium_api.core.evidence.models import (
    AnswerObject,
    ConflictItem,
    EvidenceBundle,
    Limits,
    RouteInfo,
)
from medynium_api.core.evidence.validator import AnswerRejected, short_answer, validate_statements
from medynium_api.core.session import Session
from medynium_api.core.snowflake.timing import pad
from medynium_api.core.streaming import Run
from medynium_api.features.copilot import prompts
from medynium_api.features.copilot.answers import finalize
from medynium_api.features.copilot.pack import focus_terms, patient_evidence, render, sources, when
from medynium_api.features.copilot.repository import CopilotRepository, Facts
from medynium_api.features.copilot.rules import allergy_conflicts

log = structlog.get_logger()
GAP_ONLY = (
    "None of this patient's current medicines are in the indexed sources, so nothing could be checked. "
    "That is a coverage gap, not a finding of no risk."
)


def parse_json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("not a JSON object")
    return value


def unindexed_medicines(facts: Facts) -> frozenset[str]:
    """Evidence ids of medicines with no indexed label. Medicines come first in the pack, in order (pack.py)."""
    return frozenset(f"P{i}" for i, m in enumerate(facts.meds, start=1) if not m["drug_id"])


class SafetyReview:
    def __init__(
        self,
        settings: Settings,
        repo: CopilotRepository | None = None,
        search: SearchClient | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo or CopilotRepository()
        self.search = search or SearchClient(settings)

    def _deny(
        self, session: Session, patient_id: str, started: float, question: str | None, run: Run
    ) -> None:
        write_audit(
            session,
            AuditEntry(action="DENIED_PATIENT", patient_id=patient_id, question=question, outcome="DENIED", steps=run.steps),
        )  # fmt: skip
        pad(started)
        raise not_found()

    def run(
        self,
        session: Session,
        patient_id: str,
        run: Run,
        *,
        question: str | None = None,
        route: RouteInfo | None = None,
    ) -> AnswerObject:
        started = time.monotonic()
        model = self.settings.strong_model
        info = route or RouteInfo(
            route="safety", model=model, confidence=None, cost_note="strong model"
        )
        with run.step("Checking access to this patient"):
            try:
                require_patient(session, patient_id)
            except ApiError:
                self._deny(session, patient_id, started, question, run)
        with run.step("Reading medications, labs and diagnoses") as step:
            facts = self.repo.patient_facts(session.snowflake_role, patient_id)
            if facts is None:
                log_policy_disagreement(session, patient_id)
                self._deny(session, patient_id, started, question, run)
            assert facts is not None
            records, injection, kinds = patient_evidence(facts)
            step.detail = f"{len(facts.meds)} medicines, {len(facts.labs)} labs, {len(facts.diagnoses)} diagnoses"

        drugs = {m["drug_id"]: m["drug_name"] for m in facts.meds if m["drug_id"]}
        gaps = sorted({m["drug_name"] for m in facts.meds if not m["drug_id"]})
        retrieval = Retrieval(chunks=[], checked_nothing=[], conflicts=[])
        if drugs:
            with run.step("Searching label text") as step:
                retrieval = self.search.retrieve_for_patient(drugs, focus_terms(facts))
                step.detail = f"{len(retrieval.chunks)} sections from {len(drugs) - len(retrieval.checked_nothing)} labels"
        bundle = EvidenceBundle(patient_records=records, sql=facts.sql, sources=sources(retrieval))

        draft: dict[str, Any] = {}
        prompt = prompts.load("safety_agent")
        checked = sorted({c.drug_name or "" for c in retrieval.chunks if c.drug_name})
        nothing = [drugs[d] for d in retrieval.checked_nothing]
        if retrieval.chunks:
            with run.step("Drafting the review") as step:
                draft, completion = self._draft(
                    prompt.text, render(facts, bundle, gaps, checked, nothing)
                )
                step.detail = f"{completion.model}, {completion.completion_tokens or '?'} tokens"
        with run.step("Checking each statement against its evidence") as step:
            try:
                validated = validate_statements(
                    draft, bundle, patient_id, kinds, unindexed_medicines(facts)
                )
            except AnswerRejected as exc:
                log.error("answer_rejected", reason=str(exc))
                raise ApiError(
                    ErrorCode.AGENT_UNAVAILABLE,
                    "The review could not be verified and was not shown.",
                ) from exc
            step.detail = f"{len(validated.considerations)} kept, {len(validated.dropped)} removed"
        with run.step("Running fixed rules on the record") as step:
            hits = allergy_conflicts(facts, bundle)
            if hits:  # rule findings lead, then the model's statements; ids are renumbered together
                validated.considerations = [*hits, *validated.considerations]
                for number, item in enumerate(validated.considerations, start=1):
                    item.id = f"C{number}"
                validated.rule_hits = len(hits)
            step.detail = (
                f"{len(hits)} allergy match(es)" if facts.allergies else "no allergies recorded"
            )

        short = (
            short_answer(validated, checked) if (drugs or validated.considerations) else GAP_ONLY
        )
        limits = self._limits(
            facts,
            retrieval,
            bundle,
            checked,
            nothing,
            gaps,
            validated.injection_seen or injection,
            validated,
        )
        conflicts = [
            ConflictItem(drug=g.drug_name, section=g.section, items=[s.evidence_id for s in bundle.sources if s.chunk_id in g.chunk_ids])
            for g in retrieval.conflicts
        ]  # fmt: skip
        return finalize(
            session, run, kind="SAFETY", patient_id=patient_id, short_answer=short, considerations=validated.considerations,
            limits=limits, conflicts=conflicts, bundle=bundle, route=info, question=question or "Run safety review",
            action="RUN_SAFETY_REVIEW", prompt_hash=prompt.sha256, dropped=validated.dropped,
        )  # fmt: skip

    def _draft(self, system: str, user: str) -> tuple[dict[str, Any], Completion]:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for _ in range(2):  # one repair attempt on malformed JSON, then a clean failure
            completion = complete(self.settings.strong_model, messages, max_tokens=550)
            try:
                return parse_json(completion.text), completion
            except ValueError as exc:
                messages += [
                    {"role": "assistant", "content": completion.text},
                    {
                        "role": "user",
                        "content": f"That was not valid ({exc}). Reply with ONLY the JSON object.",
                    },
                ]
        raise ApiError(
            ErrorCode.AGENT_UNAVAILABLE,
            "The review could not be drafted. The patient record is still available.",
        )

    def _limits(
        self, facts: Facts, retrieval: Retrieval, bundle: EvidenceBundle, checked: list[str], nothing: list[str],
        gaps: list[str], injection: bool, validated: Any,
    ) -> Limits:  # fmt: skip
        by_drug: dict[str, str] = {}
        for c in retrieval.chunks:
            by_drug.setdefault(
                c.drug_name or "",
                f"{c.drug_name} against {c.title} ({c.document_id}, {c.version}, effective {when(c.effective_date)})",
            )
        notes = [
            f"Knowledge snapshot {self.settings.demo_as_of_date}. Label text is US FDA labelling, not Indian regulatory text."
        ]
        if injection:
            notes.append(
                "One document contained instruction-like text. It was treated as data and ignored."
            )
        if validated.dropped:
            notes.append(
                f"{len(validated.dropped)} drafted statement(s) were removed because the evidence did not back them."
            )
        if validated.rule_hits:
            notes.append(
                f"{validated.rule_hits} conclusion(s) came from a fixed rule on the record, not from the model."
            )
        if validated.advice_seen:
            notes.append("This tool does not recommend, start, stop or dose medicines.")
        if retrieval.conflicts:
            notes.append(
                "Two sources differ for the same drug and section; both are shown, not reconciled."
            )
        return Limits(
            checked=[by_drug[d] for d in checked if d in by_drug] + [f"{d}: label searched, nothing relevant found" for d in nothing],
            not_checked=[f"{g}: not in the indexed sources, so it was not checked" for g in gaps],
            notes=notes, snapshot_date=__import__("datetime").date.fromisoformat(self.settings.demo_as_of_date),
        )  # fmt: skip
