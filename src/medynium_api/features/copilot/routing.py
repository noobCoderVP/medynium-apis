"""Routing (A-9): a small model picks a route; the server decides what actually runs.

The router sees the question, the screen name, the open patient id and the last two questions, never patient data or
document text, so an injection in data cannot steer it. It is NOT a security boundary: rule guards run independently
of it, the action allowlist is checked here and again in the executor, and entitlement runs on every route.
Fail toward caution: low confidence escalates to `safety` or asks a question, never down to `action`; a failed router
treats the request as a question, never as an action.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field, ValidationError

from medynium_api.core.config import Settings
from medynium_api.core.cortex.complete import complete
from medynium_api.core.errors import ApiError
from medynium_api.features.copilot import prompts

log = structlog.get_logger()
Route = Literal["lookup", "analyst", "knowledge", "safety", "action", "refuse"]
ACTIONS = ("open_patient", "show_timeline", "run_safety_review", "pin_evidence")
NEEDS_PATIENT = {"lookup", "analyst", "safety"}

POPULATION = re.compile(
    r"\b(all|every|each|which|how many|list|other|another)\b.{0,40}\b(patients|people)\b|\beveryone\b|\b(other|another) patient\b",
    re.IGNORECASE,
)
RECORD_CHANGE = re.compile(
    r"\b(change|update|edit|modify|delete|remove|add|set|write|enter|correct|amend|erase)\b.{0,40}\b(dose|dosage|medication|medicine|diagnosis|note|lab|result|record|chart|allergy|entry)\b",
    re.IGNORECASE,
)
PRESCRIBING = re.compile(
    r"\bwhat (should|do|can) (i|we) (prescribe|give|start|use)\b|\bshould i (prescribe|start|stop|switch|increase|reduce)\b|\bwhat dos(e|age)\b"
    r"|\bhow much\b.{0,25}\b(give|take|prescribe)\b|\bprescribe\b|\brecommend (a |an |the )?(drug|medicine|medication|treatment|dose)\b|\bdiagnos(e|is)\b",
    re.IGNORECASE,
)
RUN_REVIEW = re.compile(
    r"\b(run|do|start|perform)\b.{0,20}\bsafety (review|check)\b", re.IGNORECASE
)
REASONS = {
    "cross_patient": POPULATION,
    "record_change": RECORD_CHANGE,
    "prescribing": PRESCRIBING,
}


class Step(BaseModel):
    route: Route
    action: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    reason: str = ""


@dataclass
class Decision:
    steps: list[Step]
    model: str | None
    refuse_reason: str | None = None
    fallback: bool = False
    escalated: bool = False
    notes: list[str] = field(default_factory=list)


def guard(question: str) -> str | None:
    """A refusal reason decided by rules alone, whatever the router says."""
    for reason, pattern in REASONS.items():
        if pattern.search(question):
            return reason
    return None


def _parse(text: str) -> list[Step]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON")
    data = json.loads(text[start : end + 1])
    items = data.get("plan") if isinstance(data, dict) and "plan" in data else [data]
    if not isinstance(items, list) or not 1 <= len(items) <= 3:
        raise ValueError("plan must have one to three steps")
    return [Step.model_validate(item) for item in items]


def call_router(
    settings: Settings, question: str, screen: str, patient_id: str | None, history: list[str]
) -> list[Step]:
    prompt = prompts.load("router")
    user = (
        f"Screen: {screen}\nOpen patient: {patient_id or 'none'}\nLast questions: {json.dumps(history[-2:])}\n"
        f'Request: """{question}"""'
    )
    messages = [{"role": "system", "content": prompt.text}, {"role": "user", "content": user}]
    last: Exception | None = None
    for _ in range(2):  # retry once on a bad reply, then fall back
        try:
            reply = complete(
                settings.router_model,
                messages,
                max_tokens=300,
                timeout=settings.router_timeout_seconds,
            )
            return _parse(reply.text)
        except (ValueError, ValidationError, ApiError) as exc:
            last = exc
    raise ValueError(f"router failed: {type(last).__name__}")


def decide(
    settings: Settings, question: str, screen: str, patient_id: str | None, history: list[str]
) -> Decision:
    forced = guard(question)
    if forced:
        step = Step(route="refuse", confidence=1.0, reason=f"rule guard: {forced}")
        return Decision([step], model=None, refuse_reason=forced, notes=["rule guard"])
    try:
        steps = call_router(settings, question, screen, patient_id, history)
    except (ValueError, ApiError) as exc:
        log.warning("router_fallback", reason=str(exc))
        fallback = Step(
            route="safety", confidence=0.0, reason="router unavailable: treated as a question"
        )
        return Decision(
            [fallback],
            model=settings.router_model,
            fallback=True,
            notes=["router failed; handled as a question"],
        )

    wants_review = RUN_REVIEW.search(question) is not None
    if (  # a small router sometimes drops the second step of "open X and run the review"
        wants_review
        and steps[0].action == "open_patient"
        and not any(s.action == "run_safety_review" for s in steps)
    ):
        steps = [*steps, Step(route="action", action="run_safety_review", confidence=steps[0].confidence, reason="completed from the request text")]  # fmt: skip
    checked: list[Step] = []
    escalated = False
    for step in steps:
        if step.route == "action":
            if step.action not in ACTIONS:  # an unlisted action is refused, never run
                return Decision(
                    [Step(route="refuse", confidence=1.0, reason="unlisted action")],
                    settings.router_model,
                    "unlisted_action",
                )
        elif step.action is not None:
            step = step.model_copy(update={"action": None})
        if step.confidence < settings.router_confidence_threshold and step.route != "refuse":
            escalated = True  # escalate up to the careful route; never down to action
            step = Step(
                route="safety" if patient_id else "refuse",
                confidence=step.confidence,
                reason="low confidence: escalated",
            )
        checked.append(step)
    refuse_reason = (
        "needs_clarification"
        if any(s.route == "refuse" and "low confidence" in s.reason for s in checked)
        else None
    )
    return Decision(checked, settings.router_model, refuse_reason, escalated=escalated)
