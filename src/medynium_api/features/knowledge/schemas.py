import datetime as dt
from typing import Literal

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
    mode: Literal["search", "browse"] = "search"
    scope: list[str] = []  # drugs the results were limited to, by display name
    suggestions: list[str] = []  # nearest indexed drugs when nothing matched
    has_more: bool = False  # more sections exist than `limit` returned


class KnowledgeStatus(BaseModel):
    snapshot_date: dt.date | None
    document_count: int
    chunk_count: int
    drug_count: int
    drugs: list[str]
    not_indexed: list[
        str
    ] = []  # known to the system but with no label indexed (an honest gap, listed)
    sections: list[str] = []
    sources: list[str]
    notes: str | None


class DrugEntry(BaseModel):
    drug_id: str
    name: str  # display name, also accepted by the `drug` filter
    generic: str
    brands: list[str]
    section_count: int
    in_nlem: bool
    nlem_level: str | None


class DrugDirectory(BaseModel):
    items: list[DrugEntry]
