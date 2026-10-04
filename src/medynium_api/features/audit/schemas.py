import datetime as dt
from typing import Any

from pydantic import BaseModel

from medynium_api.core.pagination import Page


class AuditItem(BaseModel):
    audit_id: str
    occurred_at: dt.datetime
    via: str | None
    action: str
    route: str | None
    model: str | None
    confidence: float | None
    cost_note: str | None
    patient_id: str | None
    question: str | None
    answer_id: str | None
    patient_evidence_ids: list[str]
    document_ids: list[str]
    steps: list[dict[str, Any]]
    outcome: str


AuditPage = Page[AuditItem]


class SlowStep(BaseModel):
    label: str
    runs: int
    average_seconds: float


class AiMetrics(BaseModel):
    """The assistant's own activity for the caller over a window (basic observability): volume, routes, models, tools,
    how long people waited, and which steps were slowest."""

    days: int
    entries: int
    asks: int
    by_route: dict[str, int]
    outcomes: dict[str, int]
    models: dict[str, int]
    planner_models: dict[str, int]
    tools: dict[str, int]
    median_seconds: float | None
    p95_seconds: float | None
    slowest_steps: list[SlowStep]
    proposals_approved: int
    proposals_discarded: int
