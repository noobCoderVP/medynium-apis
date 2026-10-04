"""The shapes of patient intelligence: what needs attention, what changed, what is missing (agentic upgrade, phase D).
Every item carries a `source` so the screen and the assistant can open the record behind it."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal["lab", "medication", "diagnosis", "encounter", "note", "report", "finding"]
Severity = Literal["high", "moderate", "info"]
Category = Literal["MEDICATION", "LAB", "DIAGNOSIS", "VISIT", "NOTE", "DOCUMENT"]
# Where a source record lives in the patient workspace, and the table it comes from (for evidence).
TAB = {
    "lab": "labs", "medication": "medications", "diagnosis": "overview", "encounter": "timeline",
    "note": "notes", "report": "reports", "finding": "safety",
}  # fmt: skip
TABLE = {
    "lab": "CLINICAL.LAB_RESULT", "medication": "CLINICAL.MEDICATION", "diagnosis": "CLINICAL.DIAGNOSIS",
    "encounter": "CLINICAL.ENCOUNTER", "note": "CLINICAL.CLINICAL_NOTE", "report": "CLINICAL.REPORT",
    "finding": "ANALYTICS.FINDING",
}  # fmt: skip


class SourceRef(BaseModel):
    type: SourceType
    id: str | None = None
    tab: str
    query: dict[str, str] = Field(
        default_factory=dict, description="Extra URL parameters, e.g. lab=eGFR."
    )


class AttentionItem(BaseModel):
    severity: Severity
    kind: str
    title: str
    detail: str | None = None
    date: dt.date | None = None
    source: SourceRef


class ChangeItem(BaseModel):
    category: Category
    title: str
    detail: str | None = None
    date: dt.date | None = None
    direction: Literal["up", "down", "same"] | None = None
    source: SourceRef


class ChangeSet(BaseModel):
    since: dt.date
    label: str
    counts: dict[str, int]
    items: list[ChangeItem]


class GapItem(BaseModel):
    kind: str
    title: str
    detail: str | None = None
    source: SourceRef | None = None
