"""Knowledge reads under the caller's role: snapshot, drug directory, section names, brand or alias lookup and
section browsing. KNOWLEDGE holds public documents only, so none of this touches patient data (SEC-04)."""

import time
from typing import Any

from medynium_api.core.snowflake.queries import Row, fetch_all, fetch_one
from medynium_api.core.snowflake.role_session import user_cursor

CACHE_SECONDS = (
    300  # the corpus is a controlled snapshot, so names and sections change only on a re-ingest
)
_cache: dict[tuple[str, str], tuple[float, Any]] = {}

CHUNK_COLUMNS = (
    "c.CHUNK_ID, c.DOCUMENT_ID, c.DRUG_ID, c.DRUG_NAME, c.TITLE, c.SOURCE, c.SECTION_KEY, c.SECTION_NAME, "
    "c.VERSION_LABEL AS VERSION, c.EFFECTIVE_DATE, c.RETRIEVED_DATE, c.TEXT, c.PAGE_NO"
)
SECTION_ORDER = (
    "CASE c.SECTION_KEY WHEN 'boxed_warning' THEN 0 WHEN 'contraindications' THEN 1 "
    "WHEN 'warnings_and_cautions' THEN 2 WHEN 'warnings' THEN 2 WHEN 'dosage_and_administration' THEN 3 "
    "WHEN 'drug_interactions' THEN 4 WHEN 'use_in_specific_populations' THEN 5 ELSE 6 END"
)


def _cached(role: str, key: str, load: Any) -> Any:
    hit = _cache.get((role, key))
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = load()
    _cache[(role, key)] = (time.monotonic(), value)
    return value


class KnowledgeRepository:
    def status(self, role: str) -> dict[str, object]:
        with user_cursor(role) as cur:
            snapshot = fetch_one(
                cur,
                "SELECT SNAPSHOT_DATE, DOCUMENT_COUNT, CHUNK_COUNT, DRUG_COUNT, NOTES FROM KNOWLEDGE.SNAPSHOT LIMIT 1",
            )
            drugs = fetch_all(
                cur, "SELECT DISPLAY_NAME FROM KNOWLEDGE.DRUG WHERE IN_CORPUS ORDER BY DISPLAY_NAME"
            )
            sources = fetch_all(
                cur, "SELECT DISTINCT SOURCE FROM KNOWLEDGE.DOCUMENT ORDER BY SOURCE"
            )
            gaps = fetch_all(
                cur,
                "SELECT DISPLAY_NAME FROM KNOWLEDGE.DRUG WHERE NOT IN_CORPUS ORDER BY DISPLAY_NAME",
            )
        return {
            "snapshot": snapshot,
            "drugs": [d["display_name"] for d in drugs],
            "not_indexed": [g["display_name"] for g in gaps],
            "sections": self.section_names(role),
            "sources": [s["source"] for s in sources],
        }

    def snapshot_date(self, role: str) -> object:
        with user_cursor(role) as cur:
            row = fetch_one(cur, "SELECT SNAPSHOT_DATE FROM KNOWLEDGE.SNAPSHOT LIMIT 1")
        return row["snapshot_date"] if row else None

    def section_names(self, role: str) -> list[str]:
        """Section headings in the index, most safety-relevant first."""

        def load() -> list[str]:
            with user_cursor(role) as cur:
                rows = fetch_all(
                    cur,
                    f"SELECT c.SECTION_NAME, MIN({SECTION_ORDER}) AS RANK FROM KNOWLEDGE.DOCUMENT_CHUNK c "
                    "GROUP BY c.SECTION_NAME ORDER BY RANK, c.SECTION_NAME",
                )
            return [r["section_name"] for r in rows]

        names: list[str] = _cached(role, "sections", load)
        return names

    def alias_map(self, role: str) -> list[Row]:
        """Every indexed drug name, alias and Indian brand (DRUG_NAME_MAP), lower-case, for in-process matching."""

        def load() -> list[Row]:
            with user_cursor(role) as cur:
                return fetch_all(
                    cur,
                    "SELECT n.NAME_TEXT, n.NAME_KIND, d.DRUG_ID, d.DISPLAY_NAME FROM KNOWLEDGE.DRUG_NAME_MAP n "
                    "JOIN KNOWLEDGE.DRUG d ON d.DRUG_ID = n.DRUG_ID AND d.IN_CORPUS",
                )

        rows: list[Row] = _cached(role, "aliases", load)
        return rows

    def unindexed_map(self, role: str) -> list[Row]:
        """Names, aliases and brands of drugs the system knows but has no label for, so a question about one is answered
        with an explicit "no label indexed" rather than with another drug's text."""

        def load() -> list[Row]:
            with user_cursor(role) as cur:
                return fetch_all(
                    cur,
                    "SELECT n.NAME_TEXT, n.NAME_KIND, d.DRUG_ID, d.DISPLAY_NAME FROM KNOWLEDGE.DRUG_NAME_MAP n "
                    "JOIN KNOWLEDGE.DRUG d ON d.DRUG_ID = n.DRUG_ID AND NOT d.IN_CORPUS",
                )

        rows: list[Row] = _cached(role, "unindexed", load)
        return rows

    def directory(self, role: str) -> list[Row]:
        """One row per indexed drug with its section count and Indian brands."""

        def load() -> list[Row]:
            with user_cursor(role) as cur:
                drugs = fetch_all(
                    cur,
                    "SELECT d.DRUG_ID, d.DISPLAY_NAME, d.GENERIC_NAME, d.IN_NLEM, d.NLEM_LEVEL, "
                    "COUNT(c.CHUNK_ID) AS SECTION_COUNT FROM KNOWLEDGE.DRUG d "
                    "LEFT JOIN KNOWLEDGE.DOCUMENT_CHUNK c ON c.DRUG_ID = d.DRUG_ID "
                    "WHERE d.IN_CORPUS GROUP BY d.DRUG_ID, d.DISPLAY_NAME, d.GENERIC_NAME, d.IN_NLEM, d.NLEM_LEVEL "
                    "ORDER BY d.DISPLAY_NAME",
                )
                brands = fetch_all(
                    cur,
                    "SELECT DRUG_ID, NAME_TEXT FROM KNOWLEDGE.DRUG_NAME_MAP WHERE NAME_KIND = 'INDIAN_BRAND' "
                    "ORDER BY NAME_TEXT",
                )
            by_drug: dict[str, list[str]] = {}
            for b in brands:
                by_drug.setdefault(b["drug_id"], []).append(b["name_text"])
            for d in drugs:
                d["brands"] = by_drug.get(d["drug_id"], [])
            return drugs

        rows: list[Row] = _cached(role, "directory", load)
        return rows

    def browse(
        self, role: str, drug_ids: list[str], sections: list[str] | None, limit: int
    ) -> list[Row]:
        """The sections of the named drugs in reading order, without a search query."""
        marks = ", ".join(["%s"] * len(drug_ids))
        sql = f"SELECT {CHUNK_COLUMNS} FROM KNOWLEDGE.DOCUMENT_CHUNK c WHERE c.DRUG_ID IN ({marks})"
        params: list[Any] = list(drug_ids)
        if sections:
            sql += f" AND c.SECTION_NAME IN ({', '.join(['%s'] * len(sections))})"
            params += sections
        sql += f" ORDER BY c.DRUG_NAME, {SECTION_ORDER}, c.DOCUMENT_ID, c.CHUNK_INDEX LIMIT %s"
        params.append(limit)
        with user_cursor(role) as cur:
            return fetch_all(cur, sql, params)
