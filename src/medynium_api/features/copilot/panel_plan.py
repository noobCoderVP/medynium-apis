"""Recognising panel questions and checking what a step asks for, kept apart from the handler (panel.py) so the
router can use it without importing the handler. Nothing here touches the database."""

import datetime as dt
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from medynium_api.features.copilot.panel_repository import PanelFilters

Tool = Literal[
    "list_my_patients", "pending_work", "changes_since", "patients_matching", "similar_patients"
]
TOOLS: tuple[str, ...] = (
    "list_my_patients", "pending_work", "changes_since", "patients_matching", "similar_patients",
)  # fmt: skip
MAX_TOOLS = 3
SECTION = {
    "list_my_patients": "Your patients", "patients_matching": "Matching patients",
    "pending_work": "Waiting on you", "changes_since": "Changes", "similar_patients": "Similar patients",
}  # fmt: skip
SIMILAR = re.compile(
    r"\bsimilar (patients?|cases?)\b|\b(patients?|cases?) (like|similar to) (this|her|him|them|the open)\b"
    r"|\bwho else (has|had)\b|\banyone (else )?(like|similar)\b|\bhave i seen (this|a case like this) before\b",
    re.IGNORECASE,
)

# A bare "my patients" inside another question ("which of my patients have low eGFR") is NOT a list request: it goes
# to the router, which fills in filters. Only phrases that ask for the list itself are recognised here.
LIST = re.compile(
    r"\bwho (are|is) (my|on my)\b|\bpatient list\b|\bwho do i have\b|\bwho am i (seeing|treating)\b"
    r"|\b(show|list|give) (me )?(all )?(of )?my patients\b|\bmy (panel|caseload|list)\b|\bwho needs (my )?attention\b",
    re.IGNORECASE,
)
PENDING = re.compile(
    r"\bpending\b|\bwaiting\b|\boutstanding\b|\bto[- ]?do\b|\bneeds? (my )?(review|action)\b"
    r"|\bfollow[- ]?ups?\b|\boverdue\b|\bunreviewed\b|\bwhat('s| is| do i have) (left|open)\b",
    re.IGNORECASE,
)
CHANGES = re.compile(
    r"\bwhat('s| has| have)? (changed|happened|been going on|new)\b.{0,40}\b(my|across|all|patients|today|this week|since)\b"
    r"|\bany(thing)? new (with|for|across) my\b|\brecent changes\b",
    re.IGNORECASE,
)
LIST_AND = re.compile(r"\b(and|plus|also)\b", re.IGNORECASE)
OWN = re.compile(r"\b(my|all|every|across|everyone|who|which|patients)\b", re.IGNORECASE)
DAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Tool
    filters: PanelFilters = Field(default_factory=PanelFilters)
    kinds: list[str] | None = None
    patient_id: str | None = Field(default=None, max_length=20)
    since: dt.date | None = None


def since_from(question: str, as_of: dt.date) -> dt.date:
    """ "since Monday", "yesterday", "this week", "last 3 days"; a week when nothing is said."""
    text = question.lower()
    if "yesterday" in text:
        return as_of - dt.timedelta(days=1)
    if "today" in text:
        return as_of
    found = re.search(r"\blast (\d{1,3}) days?\b", text)
    if found:
        return as_of - dt.timedelta(days=min(int(found.group(1)), 365))
    for name, weekday in DAYS.items():
        if re.search(rf"\bsince {name}\b", text):
            back = (as_of.weekday() - weekday) % 7 or 7
            return as_of - dt.timedelta(days=back)
    if "this month" in text:
        return as_of.replace(day=1)
    return as_of - dt.timedelta(days=7)


def plan_for(question: str, patient_id: str | None) -> list[dict[str, Any]] | None:
    """The common panel questions, recognised without a model so they work whatever the router says. A question about
    the open patient only ("what is pending?") is scoped to that patient unless it names the whole panel."""
    if SIMILAR.search(
        question
    ):  # about the open patient: the closest of the clinician's own patients
        return [{"tool": "similar_patients", "patient_id": patient_id}]
    wants_list, wants_pending, wants_changes = (
        bool(LIST.search(question)), bool(PENDING.search(question)), bool(CHANGES.search(question)),
    )  # fmt: skip
    if wants_changes and not LIST_AND.search(question):
        wants_list = False  # "what changed across my patients" is the changes, not the list as well
    if not (wants_list or wants_pending or wants_changes):
        return None
    whole_panel = patient_id is None or bool(OWN.search(question))
    if patient_id and not whole_panel and not wants_pending:
        return None  # "what changed" with a patient open is the per-patient answer
    calls: list[dict[str, Any]] = []
    if wants_list:
        calls.append({"tool": "list_my_patients"})
    if wants_pending:
        calls.append({"tool": "pending_work", "patient_id": None if whole_panel else patient_id})
    if wants_changes and whole_panel:
        calls.append({"tool": "changes_since"})
    return calls[:MAX_TOOLS]


def validate_calls(params: dict[str, Any]) -> list[ToolCall] | None:
    """The calls a step asks for, checked against the registry and the filter schema. None means refuse: an unknown tool
    or a malformed filter never reaches the database."""
    raw = params.get("calls")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_TOOLS:
        return None
    try:
        return [ToolCall.model_validate(item) for item in raw]
    except (ValidationError, TypeError):
        return None
