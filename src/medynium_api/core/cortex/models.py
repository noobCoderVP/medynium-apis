"""Shared retrieval models. A chunk is never shown without its full citation (FR-06)."""

import datetime as dt

from pydantic import BaseModel


class Chunk(BaseModel):
    chunk_id: str
    document_id: str
    drug_id: str | None
    drug_name: str | None
    title: str
    source: str
    section_key: str | None
    section: str
    version: str | None
    effective_date: dt.date | None
    retrieved_date: dt.date | None
    page: int | None = None
    text: str
    score: float
    conflict: bool = False


class ConflictGroup(BaseModel):
    drug_id: str
    drug_name: str | None
    section: str
    chunk_ids: list[str]


class Retrieval(BaseModel):
    """What the safety review gets: chunks, plus deterministic facts about what was and was not found."""

    chunks: list[Chunk]
    checked_nothing: list[str]  # drug ids that were searched and returned nothing relevant
    conflicts: list[ConflictGroup]
