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
