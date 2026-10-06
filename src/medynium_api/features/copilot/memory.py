"""Conversation memory for follow-ups that point at the previous panel answer: "open the first one", "tell me about the
second patient and run the review", "list them". Rules only, no model. The previous answer is loaded under the caller's
own role (own answers only), the patient ids come from its stored evidence, and the steps built here still pass the
closed action set and the entitlement checks like any other step."""

import json
import re
from dataclasses import dataclass

import structlog

from medynium_api.core.evidence.models import EvidenceResponse
from medynium_api.core.evidence.store import load_evidence
from medynium_api.core.session import Session
from medynium_api.features.copilot.panel_plan import validate_calls
from medynium_api.features.copilot.panel_summary import PLAN_RECORD
from medynium_api.features.copilot.routing import RUN_REVIEW, Decision, Step

log = structlog.get_logger()
ORDINALS = {
    "first": 0, "1st": 0, "top": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3,
    "fifth": 4, "5th": 4, "last": -1,
}  # fmt: skip
POINTS_AT = re.compile(
    r"\b(open|show|see|go to|pull up|tell me about|brief me on|what changed (for|with)|how is)\b.{0,25}"
    rf"\b(the )?({'|'.join(ORDINALS)})( one| patient)?\b",
    re.IGNORECASE,
)
MORE = re.compile(
    r"^\W*(please )?(list|show|give)( me)?( all)?( of)?( them| these| those| the (patients|items|changes|details))\W*$"
    r"|^\W*(more )?details?\W*$|^\W*(show|give) (me )?(the )?details\W*$",
    re.IGNORECASE,
)
BRIEF = re.compile(r"\b(tell me about|brief me|what changed|how is|summar)", re.IGNORECASE)


@dataclass
class Remembered:
    patient_ids: list[str]
    calls: list[dict[str, object]] | None


def _recall(evidence: EvidenceResponse) -> Remembered:
    ordered = sorted(evidence.patient_records, key=lambda p: int(p.evidence_id.lstrip("P") or 0))
    ids = list(
        dict.fromkeys(p.record_id for p in ordered if p.record_type == "Patient" and p.record_id)
    )
    calls = None
    for p in ordered:
        if p.record_type == PLAN_RECORD:
            try:
                parsed = json.loads(p.value)
            except ValueError:
                break
            if validate_calls({"calls": parsed}) is not None:
                calls = parsed
    return Remembered(ids, calls)


def follow_up(session: Session, question: str, answer_id: str | None) -> Decision | None:
    """A decision for a follow-up about the previous panel answer, or None to let the normal routing handle it."""
    if not answer_id or not (POINTS_AT.search(question) or MORE.search(question)):
        return None
    try:
        evidence = load_evidence(session, answer_id)
        memory = _recall(evidence) if evidence else None
    except Exception:  # memory is a convenience; a failure never blocks the answer
        log.warning("follow_up_memory_failed")
        return None
    if memory is None or memory.calls is None:  # the previous answer was not a panel answer
        return None
    if MORE.search(question):
        step = Step(route="panel", params={"calls": memory.calls}, confidence=1.0, reason="the same panel read, now with the detail")  # fmt: skip
        return Decision(
            [step], model=None, notes=["follow-up: detail of the previous panel answer"]
        )
    found = POINTS_AT.search(question)
    if not found or not memory.patient_ids:
        return None
    index = ORDINALS[found.group(4).lower()]
    if index >= len(memory.patient_ids):
        return None
    steps = [Step(route="action", action="open_patient", params={"patient_id": memory.patient_ids[index]}, confidence=1.0, reason="the patient the clinician pointed at")]  # fmt: skip
    if RUN_REVIEW.search(question):
        steps.append(Step(route="action", action="run_safety_review", params={}, confidence=1.0, reason="asked for the review too"))  # fmt: skip
    elif BRIEF.search(question):
        tools = [
            {"tool": "get_patient_record", "args": {"kind": "SUMMARY"}},
            {"tool": "detect_changes"},
        ]
        steps.append(Step(route="agent", params={"tools": tools}, confidence=0.9, reason="a brief of the patient just opened"))  # fmt: skip
    return Decision(steps, model=None, notes=["follow-up: patient from the previous answer"])
