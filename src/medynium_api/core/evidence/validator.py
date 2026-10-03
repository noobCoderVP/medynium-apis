"""The validator (A-3): the model proposes statements, this module disposes of them.

Rules (build-plan 04, section 5):
  1. every statement needs at least one evidence id that exists in the pack, else it is dropped;
  2. tags must match the evidence: patient_fact cites patient evidence only, retrieved_source cites source chunks only,
     ai_synthesis cites both and is worded "may warrant clinician review";
  3. instruction-like text (an injected command copied into a statement) is dropped;
  4. prescribing, dosing or diagnosis advice is dropped;
  5. the short answer is built here from what survived, never taken from the model, and "no documented consideration
     found in the indexed sources" is never written as "no risk";
  6. SQL that does not name the one patient in scope rejects the whole answer.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from medynium_api.core.evidence.models import Consideration, EvidenceBundle

REVIEW_PHRASE = "may warrant clinician review"
NO_FINDING = "No documented consideration found in the indexed sources."

INSTRUCTION_LIKE = re.compile(
    r"ignore (all |any |the )?(previous|earlier|prior|above|your)|disregard (all |the |your )?(previous|earlier|prior|rules|instructions)"
    r"|instruction aimed at|system prompt|you are now|as an ai\b|list (every|all) (the )?patients?|reveal (your|the) (prompt|instructions)"
    r"|no safety review is needed",
    re.IGNORECASE,
)
ADVICE = re.compile(
    r"\byou should (start|stop|prescribe|increase|reduce|switch|discontinue|give|take)\b"
    r"|\b(i |we )?recommend(ed)? (to )?(start|stop|increas|reduc|switch|prescrib|discontinu)"
    r"|\bshould be (started|stopped|increased|reduced|discontinued|switched|prescribed)\b"
    r"|\b(increase|reduce|lower|raise) the (dose|dosage)\b|\bdiagnos(is of|ed with|e)\b|\bprescribe\b",
    re.IGNORECASE,
)
FALSE_REASSURANCE = re.compile(
    r"\bno risk\b|\bis safe\b|\bno concerns?\b|\bnothing to worry\b", re.IGNORECASE
)


class AnswerRejected(Exception):
    """The whole answer is refused (evidence or SQL outside the one patient in scope)."""


@dataclass
class Validated:
    considerations: list[Consideration]
    dropped: list[dict[str, str]] = field(default_factory=list)
    injection_seen: bool = False
    advice_seen: bool = False
    matched_sources: set[str] = field(default_factory=set)

    @property
    def has_source_statement(self) -> bool:
        return any(c.tag in ("retrieved_source", "ai_synthesis") for c in self.considerations)


def check_scope(bundle: EvidenceBundle, patient_id: str) -> None:
    """Reject the answer if any recorded SQL does not name the patient in scope."""
    for query in bundle.sql:
        if patient_id not in query.text:
            raise AnswerRejected(f"SQL {query.sql_id} does not scope to the patient")


def validate_statements(
    draft: dict[str, Any],
    bundle: EvidenceBundle,
    patient_id: str,
    kinds: dict[str, str] | None = None,
) -> Validated:
    check_scope(bundle, patient_id)
    patient_ids = {p.evidence_id for p in bundle.patient_records}
    source_ids = {s.evidence_id for s in bundle.sources}
    result = Validated(considerations=[])
    raw = draft.get("considerations") if isinstance(draft, dict) else None
    for item in raw if isinstance(raw, list) else []:
        text = str(item.get("text", "")).strip() if isinstance(item, dict) else ""
        tag = item.get("tag") if isinstance(item, dict) else None

        def drop(reason: str, text: str = text) -> None:
            result.dropped.append({"text": text[:300], "reason": reason})

        if not text or len(text) > 700:
            drop("empty or too long")
            continue
        if INSTRUCTION_LIKE.search(text):
            result.injection_seen = True
            drop("instruction-like text")
            continue
        if ADVICE.search(text):
            result.advice_seen = True
            drop("prescribing, dosing or diagnosis advice")
            continue
        if FALSE_REASSURANCE.search(text):
            drop("states reassurance instead of evidence")
            continue
        p = [e for e in dict.fromkeys(item.get("patient_evidence") or []) if e in patient_ids]
        s = [e for e in dict.fromkeys(item.get("source_evidence") or []) if e in source_ids]
        if tag == "patient_fact":
            s = []
            if not p:
                drop("no matching patient evidence")
                continue
        elif tag == "retrieved_source":
            p = []
            if not s:
                drop("no matching source evidence")
                continue
        elif tag == "ai_synthesis":
            if not (p and s):
                drop("synthesis needs both patient and source evidence")
                continue
            if REVIEW_PHRASE not in text.lower():
                drop('synthesis must be worded "may warrant clinician review"')
                continue
            if kinds is not None:
                abnormal = any(kinds.get(e) == "abnormal_lab" for e in p)
                meds = sum(1 for e in p if kinds.get(e) == "medication")
                if not (abnormal or meds >= 2):
                    drop(
                        "a conclusion needs an abnormal lab or an interaction between listed medicines"
                    )
                    continue
        else:
            drop("unknown tag")
            continue
        result.considerations.append(
            Consideration(
                id=f"C{len(result.considerations) + 1}",
                text=text,
                tag=tag,
                patient_evidence=p,
                source_evidence=s,
            )
        )
        result.matched_sources.update(s)
    if kinds is not None:
        _keep_only_used_premises(result)
    return result


def _keep_only_used_premises(result: Validated) -> None:
    """Premises (patient facts and source statements) stay only if a surviving conclusion cites them."""
    conclusions = [c for c in result.considerations if c.tag == "ai_synthesis"]
    used = {e for c in conclusions for e in (*c.patient_evidence, *c.source_evidence)}
    kept: list[Consideration] = []
    for c in result.considerations:
        cited = {*c.patient_evidence, *c.source_evidence}
        if c.tag == "ai_synthesis" or (conclusions and cited & used):
            kept.append(c)
        else:
            result.dropped.append(
                {"text": c.text[:300], "reason": "no supported conclusion uses this statement"}
            )
    for number, c in enumerate(kept, start=1):
        c.id = f"C{number}"
    result.considerations = kept
    result.matched_sources = {e for c in kept for e in c.source_evidence}


def short_answer(validated: Validated, checked_drugs: list[str]) -> str:
    """Built from what survived validation, never taken from the model (AI-03: silence is not safety)."""
    synthesis = sum(1 for c in validated.considerations if c.tag == "ai_synthesis")
    if synthesis:
        noun = "consideration" if synthesis == 1 else "considerations"
        return f"{synthesis} documented {noun} may warrant clinician review."
    if validated.has_source_statement:
        return "Documented label text relevant to this patient was found; see the statements below."
    where = f" for {', '.join(checked_drugs)}" if checked_drugs else ""
    return f"{NO_FINDING[:-1]}{where}. This is not a statement that no risk exists."
