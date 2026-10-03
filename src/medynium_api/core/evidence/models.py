"""The answer and evidence contract (SRS 6.1, AI-08, AI-09). One object feeds the Why? panel, the audit log and
the golden test. Evidence ids are scoped to one answer: P1.. patient records, Q1.. SQL, S1.. source chunks."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

# rule_check is only ever made by a code rule (features/copilot/rules.py); the validator drops it from model output.
Tag = Literal["patient_fact", "retrieved_source", "ai_synthesis", "rule_check"]
Kind = Literal["SAFETY", "CHANGED", "MEDS", "LABS", "UTIL", "SUMMARY", "ANALYST", "KNOWLEDGE"]


class Consideration(BaseModel):
    id: str
    text: str
    tag: Tag
    patient_evidence: list[str] = Field(default_factory=list)
    source_evidence: list[str] = Field(default_factory=list)


class Limits(BaseModel):
    checked: list[str] = Field(default_factory=list)
    not_checked: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    snapshot_date: dt.date | None = None


class ConflictItem(BaseModel):
    drug: str | None
    section: str | None = None
    items: list[str]


class RouteInfo(BaseModel):
    route: str
    model: str | None = None
    confidence: float | None = None
    cost_note: str | None = None


class AnswerObject(BaseModel):
    answer_id: str
    kind: Kind
    patient_id: str | None
    short_answer: str
    considerations: list[Consideration]
    limits: Limits
    conflicts: list[ConflictItem] = Field(default_factory=list)
    route: RouteInfo | None = None
    created_at: dt.datetime


class PatientEvidence(BaseModel):
    evidence_id: str
    record_type: str
    record_id: str | None
    table: str
    value: str
    date: dt.date | None = None


class SqlEvidence(BaseModel):
    sql_id: str
    role: str
    text: str
    row_count: int
    ran_at: dt.datetime


class SourceEvidence(BaseModel):
    evidence_id: str
    chunk_id: str
    document_id: str
    title: str
    source: str
    section: str
    version: str | None
    effective_date: dt.date | None
    retrieved_date: dt.date | None
    text: str
    matched: bool = False


class EvidenceBundle(BaseModel):
    patient_records: list[PatientEvidence] = Field(default_factory=list)
    sql: list[SqlEvidence] = Field(default_factory=list)
    sources: list[SourceEvidence] = Field(default_factory=list)


class EvidenceResponse(BaseModel):
    answer_id: str
    patient_id: str | None
    created_at: dt.datetime
    route: RouteInfo | None
    patient_records: list[PatientEvidence]
    sql: list[SqlEvidence]
    sources: list[SourceEvidence]
    statement_map: dict[str, list[str]]
    dropped_statements: list[dict[str, str]]
    snapshot_date: dt.date | None
