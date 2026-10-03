import datetime as dt

from pydantic import BaseModel


class Citation(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    source: str
    drug: str | None
    section: str
    version: str | None
    effective_date: dt.date | None
    retrieved_date: dt.date | None
    page: int | None
    snippet: str
    text: str
    score: float
    conflict: bool = False


class SearchResponse(BaseModel):
    snapshot_date: dt.date | None
    items: list[Citation]
    message: str | None = None
    resolved: dict[str, str] = {}
    conflicts: list[str] = []


class KnowledgeStatus(BaseModel):
    snapshot_date: dt.date | None
    document_count: int
    chunk_count: int
    drug_count: int
    drugs: list[str]
    sources: list[str]
    notes: str | None
