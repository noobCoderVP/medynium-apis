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
from medynium_api.features.copilot.agent_plan import validate_agent_tools
from medynium_api.features.copilot.panel_plan import plan_for, validate_calls
from medynium_api.features.copilot.proposals import PROPOSE_KINDS

log = structlog.get_logger()
Route = Literal[
    "lookup",
    "analyst",
    "knowledge",
    "drug",
    "safety",
    "panel",
    "agent",
    "propose",
    "action",
    "refuse",
]
ACTIONS = ("open_patient", "show_timeline", "run_safety_review", "pin_evidence")
NEEDS_PATIENT = {"lookup", "analyst", "safety", "agent", "propose"}

# What stays refused: patients beyond the caller's own (the whole system, other clinicians' patients). Questions about
# the caller's own panel ("which of my patients...", "who is on metformin") are answered by the panel tools.
POPULATION = re.compile(
    r"\b(database|hospital|clinic-?wide|system-?wide|entire (system|hospital|clinic|database)|everyone in the|"
    r"every patient in|all (the )?patients (in|of|at) the|"
    r"(other|another|different) (doctor|clinician|physician|user|nurse|assistant)s?|someone else's|"
    r"(other|another) patient|"
    r"(dr|doctor|nurse)\.? [a-z]+('s)? patients|patients (does|of) (dr|doctor))\b",
    re.IGNORECASE,
)
RECORD_CHANGE = re.compile(
    r"\b(change|update|edit|modify|delete|remove|correct|amend|erase)\b.{0,40}\b(dose|dosage|medication|medicine|diagnosis|note|lab|result|record|chart|allergy|entry)\b"
    # a write to many patients at once is never prepared: a proposal is for the one open patient
    r"|\b(add|record|write|enter|set)\b.{0,40}\b(all|every|each)\b.{0,25}\bpatients?\b",
    re.IGNORECASE,
)
# Only a diagnosis is refused outright. Questions about medicines, doses and options for a condition are answered by the
# drug route from label text, as documented information the clinician weighs.
DIAGNOSIS = re.compile(
    r"\bdiagnose\b|\bmake a diagnosis\b|\bwhat is (the )?(diagnosis|wrong with)\b|\bwhat (does|do) (he|she|they) have\b",
    re.IGNORECASE,
)
# Plain drug-information questions, recognised by rule so they work even when the router is down.
DRUG_INFO = re.compile(
    r"\bwhat (should|can|could|do) (i|we) (prescribe|give|start|use|try)\b|\bshould i (prescribe|start|give|use|try)\b"
    r"|\bprescrib(e|ing)\b|\b(which|what) (drugs?|medicines?|antibiotics?|tablets?|treatments?|therap(y|ies)|options?)\b.{0,50}\b(for|treat|treating|against)\b"
    r"|\b(treatment|therapy|drug|medicine|antibiotic)s? (options? |choices? )?(for|to treat)\b|\balternatives? (to|for)\b"
    r"|\b(side effects?|adverse (effects|reactions)|contraindications?|indications?|interactions?|dos(e|age|ing)) (of|for|with)\b"
    r"|\b(usual|typical|standard|label|recommended|adult|paediatric|pediatric) dos(e|age)\b|\bwhat (is|are) \w+ (used|indicated) for\b|\bused (for|to treat)\b",
    re.IGNORECASE,
)
# "add a note...", "record a penicillin allergy...": the small planner sometimes mistakes these for edits.
ADD_INTENT = re.compile(r"^\s*(please\s+)?(add|record|log|enter|note down)\b", re.IGNORECASE)
REPORT_WORDS = re.compile(r"\b(report|reports|pdf|uploaded|discharge summary)\b", re.IGNORECASE)
RUN_REVIEW = re.compile(
    r"\b(run|do|start|perform)\b.{0,20}\bsafety (review|check)\b", re.IGNORECASE
)
REASONS = {
    "cross_patient": POPULATION,
    "record_change": RECORD_CHANGE,
    "diagnosis": DIAGNOSIS,
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
    settings: Settings, question: str, screen: str, patient_id: str | None, history: list[str],
    used: dict[str, str], topics: list[str] | None = None,
) -> list[Step]:  # fmt: skip
    prompt = prompts.load("router")
    user = (
        f"Today: {settings.as_of_iso}\nScreen: {screen}\nOpen patient: {patient_id or 'none'}\nLast questions: {json.dumps(history[-2:])}\n"
        f"Topics of the previous answer: {json.dumps(topics or [])}\n"
        f'Request: """{question}"""'
    )
    messages = [{"role": "system", "content": prompt.text}, {"role": "user", "content": user}]
    last: Exception | None = None
    # The fast model plans first (1 to 3 s). If its reply is unusable or names a tool that does not exist, the larger
    # planner model tries once (6 to 9 s); if that also fails, the caller falls back to the careful route.
    for model, timeout in (
        (settings.router_model, settings.router_timeout_seconds),
        (settings.planner_model, settings.planner_timeout_seconds),
    ):
        try:
            reply = complete(model, messages, max_tokens=500, timeout=timeout)
            steps = _parse(reply.text)
            if any(s.route == "agent" and validate_agent_tools(s.params) is None for s in steps):
                raise ValueError("plan names a tool that does not exist")
            if any(
                s.route == "propose" and s.params.get("kind") not in PROPOSE_KINDS for s in steps
            ):
                raise ValueError("plan names a change that does not exist")
            if (
                model == settings.router_model
                and (ADD_INTENT.search(question) or REPORT_WORDS.search(question) or bool(history))
                and any(s.route == "refuse" for s in steps)
            ):
                raise ValueError("refused a request to add something; the larger planner decides")
            used["model"] = model
            return steps
        except (ValueError, ValidationError, ApiError) as exc:
            last = exc
    raise ValueError(f"router failed: {type(last).__name__}")


def decide(
    settings: Settings, question: str, screen: str, patient_id: str | None, history: list[str],
    topics: list[str] | None = None,
) -> Decision:  # fmt: skip
    forced = guard(question)
    if forced:
        step = Step(route="refuse", confidence=1.0, reason=f"rule guard: {forced}")
        return Decision([step], model=None, refuse_reason=forced, notes=["rule guard"])
    # A request to add something or to read a report is never a panel question, whatever words it shares with one
    # ("add a note: follow up in two weeks", "what follow-up does the report recommend").
    own_work = ADD_INTENT.search(question) or REPORT_WORDS.search(question)
    panel = None if own_work else plan_for(question, patient_id)
    if panel:  # the common panel questions need no model, so they work even when the router is down
        step = Step(
            route="panel",
            params={"calls": panel},
            confidence=1.0,
            reason="panel question recognised",
        )
        return Decision(
            [step], model=None, notes=["panel question recognised by rule, no model call"]
        )
    # Drug information needs no router: on the Knowledge screen every question is one, elsewhere the usual phrasings are.
    # The drug route only reads label text (and, with a patient open, that patient's own record), so it is safe to
    # choose by rule.
    if screen == "knowledge" or (DRUG_INFO.search(question) and not own_work):
        step = Step(route="drug", confidence=1.0, reason="drug information question recognised")
        return Decision(
            [step], model=None, notes=["drug question recognised by rule, no router call"]
        )
    try:
        used: dict[str, str] = {}
        steps = call_router(settings, question, screen, patient_id, history, used, topics)
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
                    used.get("model"),
                    "unlisted_action",
                )
        elif step.action is not None:
            step = step.model_copy(update={"action": None})
        if step.route == "agent" and validate_agent_tools(step.params) is None:
            return Decision(  # an unknown tool or a bad argument never runs
                [Step(route="refuse", confidence=1.0, reason="agent request not understood")],
                used.get("model"),
                "needs_clarification",
            )
        if step.route == "propose" and (
            step.params.get("kind") not in PROPOSE_KINDS
            or not isinstance(step.params.get("args", {}), dict)
        ):
            return Decision(
                [Step(route="refuse", confidence=1.0, reason="proposal not understood")],
                used.get("model"),
                "needs_clarification",
            )
        if step.route == "panel" and validate_calls(step.params) is None:
            return Decision(  # an unknown tool or a malformed filter never reaches the database
                [Step(route="refuse", confidence=1.0, reason="panel request not understood")],
                used.get("model"),
                "needs_clarification",
            )
        if (
            step.confidence < settings.router_confidence_threshold
            and step.route
            not in (
                "refuse",
                "drug",
            )  # drug only reads labels, so low confidence needs no escalation
        ):
            escalated = True  # escalate up to the careful route; never down to action
            step = Step(
                route="safety" if patient_id and step.route != "panel" else "refuse",
                confidence=step.confidence,
                reason="low confidence: escalated",
            )
        checked.append(step)
    refuse_reason = (
        "needs_clarification"
        if any(s.route == "refuse" and "low confidence" in s.reason for s in checked)
        else None
    )
    return Decision(checked, used.get("model"), refuse_reason, escalated=escalated)
