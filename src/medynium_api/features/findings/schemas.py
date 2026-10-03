import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["NEW", "ACKNOWLEDGED", "FLAGGED", "DISMISSED", "ESCALATED"]


class FindingCreate(BaseModel):
    """Raise a finding from one statement of one of the caller's own answers."""

    model_config = ConfigDict(extra="forbid")

    answer_id: str = Field(min_length=3, max_length=40)
    consideration_id: str = Field(min_length=1, max_length=20)


class FindingUpdate(BaseModel):
    """A decision. Dismissing needs a reason, flagging needs a follow-up date, escalating needs a colleague."""

    model_config = ConfigDict(extra="forbid")

    status: Status
    reason: str | None = Field(default=None, max_length=500)
    follow_up_on: dt.date | None = None
    assigned_to: str | None = Field(default=None, max_length=64)


class Finding(BaseModel):
    finding_id: str
    patient_id: str
    answer_id: str
    consideration_id: str
    summary: str
    status: Status
    reason: str | None
    follow_up_on: dt.date | None
    assigned_to: str | None
    assigned_to_name: str | None
    created_by_name: str | None
    created_at: dt.datetime
    updated_at: dt.datetime | None


class FindingList(BaseModel):
    items: list[Finding]
    open_count: int


class Colleague(BaseModel):
    user_id: str
    name: str
    role: str


class ColleagueList(BaseModel):
    items: list[Colleague]
