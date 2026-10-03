"""Knowledge search with full citations and honest gaps (K-7). Free text, brand names and aliases are resolved to
generics; nothing is invented when nothing matches."""

import re
from itertools import pairwise
from typing import Any

from medynium_api.core.config import Settings
from medynium_api.core.cortex.models import Chunk
from medynium_api.core.cortex.search_client import SearchClient, flag_conflicts
from medynium_api.core.session import Session
from medynium_api.features.knowledge.repository import KnowledgeRepository
from medynium_api.features.knowledge.schemas import Citation, KnowledgeStatus, SearchResponse

NOT_FOUND_MESSAGE = "No matching section in the indexed sources."


def _snippet(text: str, query: str, width: int = 260) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 3]
    lowered = text.lower()
    hits = [lowered.find(w) for w in words if lowered.find(w) >= 0]
    start = max(0, (min(hits) if hits else 0) - 60)
    piece = text[start : start + width].strip()
    return ("..." if start else "") + piece + ("..." if start + width < len(text) else "")


def _citation(chunk: Chunk, query: str) -> Citation:
    return Citation(
        chunk_id=chunk.chunk_id, document_id=chunk.document_id, title=chunk.title, source=chunk.source,
        drug=chunk.drug_name, section=chunk.section, version=chunk.version, effective_date=chunk.effective_date,
        retrieved_date=chunk.retrieved_date, page=chunk.page, snippet=_snippet(chunk.text, query),
        text=chunk.text, score=round(chunk.score, 3), conflict=chunk.conflict,
    )  # fmt: skip


class KnowledgeService:
    def __init__(
        self,
        settings: Settings,
        repo: KnowledgeRepository | None = None,
        client: SearchClient | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo or KnowledgeRepository()
        self.client = client or SearchClient(settings)

    def search(
        self, session: Session, q: str, drug: str | None, section: str | None, limit: int
    ) -> SearchResponse:
        role = session.snowflake_role
        words = re.findall(r"[a-z0-9][a-z0-9-]*", " ".join(filter(None, [q, drug])).lower())
        matches = self.repo.resolve_names(
            role, list({*words, *(f"{a} {b}" for a, b in pairwise(words))})
        )
        drug_ids = sorted({m["drug_id"] for m in matches})
        resolved = {m["name_text"]: m["display_name"] for m in matches}
        query = q
        if drug_ids:  # swap each brand for its generic so the brand finds its label text
            brands = {m["name_text"] for m in matches if m["name_kind"] == "INDIAN_BRAND"}
            rest = " ".join(w for w in re.findall(r"[A-Za-z0-9-]+", q) if w.lower() not in brands)
            query = f"{rest} {' '.join(sorted({m['display_name'] for m in matches}))}".strip()
        chunks = self.client.search(query, drug_ids=drug_ids or None, section=section, limit=limit)
        snapshot: Any = self.repo.snapshot_date(role)
        conflicts = flag_conflicts(chunks)
        return SearchResponse(
            snapshot_date=snapshot,
            items=[_citation(c, q) for c in chunks],
            message=None if chunks else NOT_FOUND_MESSAGE,
            resolved=resolved,
            conflicts=[f"{g.drug_name}: {g.section}" for g in conflicts],
        )

    def status(self, session: Session) -> KnowledgeStatus:
        data: Any = self.repo.status(session.snowflake_role)
        snap = data["snapshot"] or {}
        return KnowledgeStatus(
            snapshot_date=snap.get("snapshot_date"), document_count=int(snap.get("document_count") or 0),
            chunk_count=int(snap.get("chunk_count") or 0), drug_count=int(snap.get("drug_count") or 0),
            drugs=data["drugs"], sources=data["sources"], notes=snap.get("notes"),
        )  # fmt: skip
