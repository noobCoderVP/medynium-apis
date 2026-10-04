import datetime as dt
from typing import Literal

from pydantic import BaseModel

from medynium_api.core.intel.models import AttentionItem, ChangeSet, GapItem, SourceRef


class AttentionResponse(BaseModel):
    patient_id: str
    as_of: dt.date
    items: list[AttentionItem]
    counts: dict[str, int]


class GapResponse(BaseModel):
    patient_id: str
    items: list[GapItem]


class LatestResult(BaseModel):
    name: str
    value: str
    unit: str | None
    flag: str | None
    date: dt.date | None
    previous: str | None
    source: SourceRef


class BriefResponse(BaseModel):
    """The first screen of a patient: what to look at, what changed, what is missing. Rules only, no model call."""

    patient_id: str
    name: str
    age: int
    sex: str
    as_of: dt.date
    headline: str
    attention: AttentionResponse
    changes: ChangeSet
    gaps: list[GapItem]
    latest_results: list[LatestResult]


class SummaryResponse(BaseModel):
    patient_id: str
    summary: str
    source: Literal["model", "rules"]
    model: str | None = None


class PatientSummary(BaseModel):
    """The stored written summary (markdown) of a patient, or `exists=false` before the first one is written."""

    patient_id: str
    exists: bool
    markdown: str | None = None
    source: Literal["model", "rules"] | None = None
    model: str | None = None
    generated_at: dt.datetime | None = None
    generated_by: str | None = None
    changed_since: bool = False
