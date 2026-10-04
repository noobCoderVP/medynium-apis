import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal[
    "ESCALATED_FINDING",
    "FOLLOW_UP",
    "OPEN_FINDING",
    "REPORT_TO_REVIEW",
    "ABNORMAL_LAB",
    "RECENT_EMERGENCY",
]


class PendingItem(BaseModel):
    item_id: str
    patient_id: str
    patient_name: str
    kind: Kind
    title: str
    detail: str
    due_date: dt.date | None = None
    overdue: bool = Field(description="A follow-up whose date has passed (against the as-of date).")
    raised_at: dt.datetime | None
    source_table: str
    source_id: str | None = Field(description="The record behind the item, for the evidence link.")


class PendingPage(BaseModel):
    items: list[PendingItem]
    total: int
    limit: int
    offset: int
    as_of: dt.date


class PendingSummary(BaseModel):
    total: int
    overdue: int
    by_kind: dict[str, int]
    as_of: dt.date


class LabReviewed(BaseModel):
    lab_id: str
    patient_id: str
    reviewed_at: dt.datetime
