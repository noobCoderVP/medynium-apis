"""Cortex Search over the public document chunks, and retrieval for a patient's drugs (K-6).

Retrieval is filtered by metadata first (the patient's drugs), ranked second, capped per drug so one verbose label
cannot crowd out the others, and honest about gaps: a drug that returns nothing relevant is reported as checked,
not guessed at. The model never decides what is missing from the index.
"""

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import structlog

from medynium_api.core.config import Settings
from medynium_api.core.cortex.auth import rest_headers
from medynium_api.core.cortex.models import Chunk, ConflictGroup, Retrieval
from medynium_api.core.errors import ApiError, ErrorCode

log = structlog.get_logger()
COLUMNS = [
    "CHUNK_ID", "DOCUMENT_ID", "DRUG_ID", "DRUG_NAME", "TITLE", "SOURCE", "SECTION_KEY", "SECTION_NAME",
    "VERSION_LABEL", "EFFECTIVE_DATE", "RETRIEVED_DATE", "TEXT", "PAGE_NO",
]  # fmt: skip
SAFETY_SECTIONS = {
    "boxed_warning": 0.10,
    "contraindications": 0.10,
    "warnings_and_cautions": 0.08,
    "warnings": 0.08,
    "use_in_specific_populations": 0.06,
    "dosage_and_administration": 0.05,
}  # small additive boost when the safety review retrieves; free-text search is unboosted
# Tuned on knowledge/eval (K-8): unresolved free text must clear 0.50 so a drug outside the corpus returns a clean
# gap; once a drug is named or resolved the search is filtered to it, and a low floor is enough.
MIN_COSINE = 0.50
FILTERED_MIN_COSINE = 0.30
PER_DRUG = 3
TOTAL = 8


def _date(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


class SearchClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None) -> None:
        self.settings = settings
        self.http = http or httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
        db, schema, name = settings.cortex_search_service.split(".")
        self.url = (
            f"https://{settings.snowflake_host}/api/v2/databases/{db}/schemas/{schema}"
            f"/cortex-search-services/{name}:query"
        )

    def search(
        self,
        query: str,
        *,
        drug_ids: list[str] | None = None,
        section: str | None = None,
        limit: int = 5,
    ) -> list[Chunk]:
        body: dict[str, Any] = {"query": query, "columns": COLUMNS, "limit": limit}
        clauses: list[dict[str, Any]] = []
        if drug_ids:
            clauses.append({"@or": [{"@eq": {"DRUG_ID": d}} for d in drug_ids]})
        if section:
            clauses.append({"@eq": {"SECTION_NAME": section}})
        if clauses:
            body["filter"] = clauses[0] if len(clauses) == 1 else {"@and": clauses}
        try:
            response = self.http.post(self.url, headers=rest_headers(self.settings), json=body)
        except httpx.TimeoutException as exc:
            raise ApiError(ErrorCode.TIMEOUT, "Knowledge search timed out.") from exc
        except httpx.HTTPError as exc:
            raise ApiError(ErrorCode.AGENT_UNAVAILABLE, "Knowledge search is unavailable.") from exc
        if response.status_code != 200:
            log.error("search_failed", status=response.status_code)
            raise ApiError(ErrorCode.AGENT_UNAVAILABLE, "Knowledge search is unavailable.")
        chunks = []
        for row in response.json().get("results", []):
            scores = row.get("@scores", {})
            chunks.append(
                Chunk(
                    chunk_id=row["CHUNK_ID"], document_id=row["DOCUMENT_ID"], drug_id=row.get("DRUG_ID"),
                    drug_name=row.get("DRUG_NAME"), title=row["TITLE"], source=row["SOURCE"],
                    section_key=row.get("SECTION_KEY"), section=row["SECTION_NAME"], version=row.get("VERSION_LABEL"),
                    effective_date=_date(row.get("EFFECTIVE_DATE")), retrieved_date=_date(row.get("RETRIEVED_DATE")),
                    page=int(row["PAGE_NO"]) if row.get("PAGE_NO") else None, text=row["TEXT"],
                    score=float(scores.get("cosine_similarity", scores.get("reranker_score", 0.0))),
                )
            )  # fmt: skip
        floor = FILTERED_MIN_COSINE if drug_ids else MIN_COSINE
        return [c for c in chunks if c.score >= floor]

    def retrieve_for_patient(
        self,
        drugs: dict[str, str],
        focus_terms: str,
        *,
        per_drug: int = PER_DRUG,
        total: int = TOTAL,
    ) -> Retrieval:
        """For each in-corpus drug (id -> name) fetch its most relevant chunks, capped per drug and in total."""

        def one(item: tuple[str, str]) -> tuple[str, list[Chunk]]:
            drug_id, name = item
            found = self.search(f"{name} {focus_terms}", drug_ids=[drug_id], limit=per_drug + 4)
            found.sort(
                key=lambda c: c.score + SAFETY_SECTIONS.get(c.section_key or "", 0.0), reverse=True
            )
            return drug_id, found[:per_drug]

        with ThreadPoolExecutor(max_workers=max(1, min(4, len(drugs)))) as pool:
            results = list(pool.map(one, drugs.items()))
        checked_nothing = [d for d, found in results if not found]
        chunks: list[Chunk] = []
        rank = 0
        while len(chunks) < total and any(
            rank < len(found) for _, found in results
        ):  # round-robin across drugs
            for _, found in results:
                if rank < len(found) and len(chunks) < total:
                    chunks.append(found[rank])
            rank += 1
        return Retrieval(
            chunks=chunks, checked_nothing=checked_nothing, conflicts=flag_conflicts(chunks)
        )


def flag_conflicts(chunks: list[Chunk]) -> list[ConflictGroup]:
    """Two chunks for the same drug and section from different documents or versions: show both, never reconcile (AI-06)."""
    groups: dict[tuple[str, str], list[Chunk]] = {}
    for chunk in chunks:
        if chunk.drug_id and chunk.section_key:
            groups.setdefault((chunk.drug_id, chunk.section_key), []).append(chunk)
    found = []
    for (drug_id, _), items in groups.items():
        if len({c.document_id for c in items}) > 1:
            for c in items:
                c.conflict = True
            found.append(
                ConflictGroup(
                    drug_id=drug_id,
                    drug_name=items[0].drug_name,
                    section=items[0].section,
                    chunk_ids=[c.chunk_id for c in items],
                )
            )
    return found
