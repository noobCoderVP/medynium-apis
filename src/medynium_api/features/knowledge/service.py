"""Knowledge search with full citations and honest gaps (K-7). Free text, brand names, aliases and small typos are
resolved to generics; a drug on its own browses its sections; nothing is invented when nothing matches."""

import re
from typing import Any

from medynium_api.core.config import Settings
from medynium_api.core.cortex.models import Chunk
from medynium_api.core.cortex.search_client import SearchClient, flag_conflicts
from medynium_api.core.errors import ApiError, ErrorCode
from medynium_api.core.session import Session
from medynium_api.features.knowledge.names import (
    match_drugs,
    match_sections,
    suggest_drugs,
    ungrounded,
    words,
)
from medynium_api.features.knowledge.repository import KnowledgeRepository
from medynium_api.features.knowledge.schemas import (
    Citation,
    DrugDirectory,
    DrugEntry,
    KnowledgeStatus,
    SearchResponse,
)

NOT_FOUND_MESSAGE = "No matching section in the indexed sources."
STRONG = 0.50  # a match this close needs no lexical check
TOPIC_FLOOR = 0.34  # unfiltered topic words ("renal", "pregnancy") score 0.35 to 0.49; unrelated text stays under 0.30
DRUG_FLOOR = 0.30  # once a drug is named the search is filtered to it, so a low floor is enough


def _snippet(text: str, query: str, width: int = 260) -> str:
    terms = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 3]
    lowered = text.lower()
    hits = [lowered.find(w) for w in terms if lowered.find(w) >= 0]
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


def _chunk(row: dict[str, Any]) -> Chunk:
    return Chunk(
        chunk_id=row["chunk_id"], document_id=row["document_id"], drug_id=row["drug_id"],
        drug_name=row["drug_name"], title=row["title"], source=row["source"], section_key=row["section_key"],
        section=row["section_name"], version=row["version"], effective_date=row["effective_date"],
        retrieved_date=row["retrieved_date"], page=row["page_no"], text=row["text"], score=1.0,
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
        self, session: Session, q: str | None, drug: str | None, section: str | None, limit: int
    ) -> SearchResponse:
        text = (q or "").strip()
        if not text and not (drug or "").strip():
            raise ApiError(ErrorCode.INVALID_REQUEST, "Give a search text or choose a drug.")
        role = session.snowflake_role
        aliases = self.repo.alias_map(role)
        snapshot: Any = self.repo.snapshot_date(role)
        base = SearchResponse(snapshot_date=snapshot, items=[], mode="search" if text else "browse")

        picked = match_drugs(drug, aliases) if drug and drug.strip() else []
        if drug and drug.strip() and not picked:
            return self._gap(
                role,
                base,
                self._not_indexed(role, drug) or f"'{drug.strip()}' is not an indexed drug.",
                drug,
            )
        found = picked or match_drugs(text, aliases)
        if text and not found:
            known = self._not_indexed(role, text)
            if (
                known
            ):  # a recognised drug with no label: say so, never answer with another drug's text
                return self._gap(role, base, known, text)
        drug_ids = sorted({m["drug_id"] for m in found})
        base.scope = sorted({m["display_name"] for m in found}) if picked else []
        base.resolved = {
            m["name_text"]: m["display_name"]
            for m in found
            if m["name_kind"] == "INDIAN_BRAND"
            or m["name_text"] not in {m["display_name"].lower(), *words(m["display_name"])}
        }

        sections: list[str] | None = None
        if section and section.strip():
            sections = match_sections(section, self.repo.section_names(role))
            if not sections:
                names = ", ".join(self.repo.section_names(role))
                return self._gap(
                    role, base, f"No section named '{section.strip()}'. Sections: {names}."
                )

        if not text:
            rows = self.repo.browse(role, drug_ids, sections, limit + 1)
            chunks = [_chunk(r) for r in rows[:limit]]
            base.has_more = len(rows) > limit
            text = " ".join(base.scope)
        else:
            chunks = self.client.search(
                self._query(text, found),
                drug_ids=drug_ids or None,
                section=sections,
                limit=limit,
                min_score=DRUG_FLOOR if drug_ids else TOPIC_FLOOR,
            )
        weak = chunks and not drug_ids and max(c.score for c in chunks) < STRONG
        if weak and ungrounded(
            text, [c.text for c in chunks]
        ):  # asks about what the index never mentions
            chunks = []
        base.has_more = base.has_more or (base.mode == "search" and len(chunks) >= limit)
        base.conflicts = [f"{g.drug_name}: {g.section}" for g in flag_conflicts(chunks)]
        base.items = [_citation(c, text) for c in chunks]
        if not chunks:
            return self._gap(role, base, NOT_FOUND_MESSAGE, text)
        return base

    def _not_indexed(self, role: str, text: str) -> str | None:
        missing = match_drugs(text, self.repo.unindexed_map(role))
        if not missing:
            return None
        names = ", ".join(sorted({m["display_name"] for m in missing}))
        return (
            f"{names}: a recognised drug, but no label is indexed for it. The corpus is built from US labels, and none "
            "is available or added for this one. Nothing is guessed from other drugs."
        )

    @staticmethod
    def _query(text: str, found: list[dict[str, Any]]) -> str:
        """Swap each brand or misspelling for its generic so the text finds the label wording."""
        if not found:
            return text
        used = {m["name_text"] for m in found}
        rest = " ".join(w for w in re.findall(r"[A-Za-z0-9-]+", text) if w.lower() not in used)
        return f"{rest} {' '.join(sorted({m['display_name'] for m in found}))}".strip()

    def _gap(
        self, role: str, response: SearchResponse, message: str, near: str | None = None
    ) -> SearchResponse:
        """An honest empty result: say so, and offer the closest indexed drugs."""
        response.items = []
        response.message = message
        if near:
            names = [d["display_name"] for d in self.repo.directory(role)]
            response.suggestions = suggest_drugs(near, names)
        return response

    def drugs(self, session: Session) -> DrugDirectory:
        return DrugDirectory(
            items=[
                DrugEntry(
                    drug_id=d["drug_id"],
                    name=d["display_name"],
                    generic=d["generic_name"],
                    brands=d["brands"],
                    section_count=int(d["section_count"] or 0),
                    in_nlem=bool(d["in_nlem"]),
                    nlem_level=d["nlem_level"],
                )
                for d in self.repo.directory(session.snowflake_role)
            ]
        )

    def status(self, session: Session) -> KnowledgeStatus:
        data: Any = self.repo.status(session.snowflake_role)
        snap = data["snapshot"] or {}
        return KnowledgeStatus(
            snapshot_date=snap.get("snapshot_date"), document_count=int(snap.get("document_count") or 0),
            chunk_count=int(snap.get("chunk_count") or 0), drug_count=int(snap.get("drug_count") or 0),
            drugs=data["drugs"], not_indexed=data["not_indexed"], sections=data["sections"], sources=data["sources"], notes=snap.get("notes"),
        )  # fmt: skip
