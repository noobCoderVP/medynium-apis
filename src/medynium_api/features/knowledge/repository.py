"""Knowledge reads under the caller's role: snapshot, drug list and brand or alias resolution. KNOWLEDGE holds
public documents only, so none of this touches patient data (SEC-04)."""

from medynium_api.core.snowflake.queries import Row, fetch_all, fetch_one
from medynium_api.core.snowflake.role_session import user_cursor


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
        return {
            "snapshot": snapshot,
            "drugs": [d["display_name"] for d in drugs],
            "sources": [s["source"] for s in sources],
        }

    def snapshot_date(self, role: str) -> object:
        with user_cursor(role) as cur:
            row = fetch_one(cur, "SELECT SNAPSHOT_DATE FROM KNOWLEDGE.SNAPSHOT LIMIT 1")
        return row["snapshot_date"] if row else None

    def resolve_names(self, role: str, tokens: list[str]) -> list[Row]:
        """Match query words against drug aliases and Indian brand names (DRUG_NAME_MAP)."""
        if not tokens:
            return []
        marks = ", ".join(["%s"] * len(tokens))
        with user_cursor(role) as cur:
            return fetch_all(
                cur,
                f"SELECT n.NAME_TEXT, n.NAME_KIND, d.DRUG_ID, d.DISPLAY_NAME FROM KNOWLEDGE.DRUG_NAME_MAP n "
                f"JOIN KNOWLEDGE.DRUG d ON d.DRUG_ID = n.DRUG_ID AND d.IN_CORPUS WHERE n.NAME_TEXT IN ({marks})",
                tokens,
            )
