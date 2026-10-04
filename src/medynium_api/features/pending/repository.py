"""Pending work under the caller's role: the entitled-patient policy decides what is visible. The one write is the
"mark reviewed" row for an abnormal lab, inserted under the caller's role (a doctor, who holds INSERT on it)."""

from medynium_api.core.panel_sql import pending_query
from medynium_api.core.snowflake.queries import Row, execute, fetch_all, fetch_one
from medynium_api.core.snowflake.role_session import user_cursor


class PendingRepository:
    def page(
        self, role: str, kinds: list[str] | None, patient_id: str | None, limit: int, offset: int
    ) -> tuple[list[Row], int]:
        sql, params = pending_query(kinds, patient_id)
        with user_cursor(role) as cur:
            rows = fetch_all(cur, sql, [*params, limit, offset])
        return rows, int(rows[0]["total"]) if rows else 0

    def counts(self, role: str) -> dict[str, int]:
        sql, params = pending_query(None, None, count=True)
        with user_cursor(role) as cur:
            return {r["kind"]: int(r["n"]) for r in fetch_all(cur, sql, params)}

    def overdue(self, role: str, as_of: str) -> int:
        with user_cursor(role) as cur:
            row = fetch_one(
                cur,
                "SELECT COUNT(*) AS N FROM ANALYTICS.PENDING_ITEM WHERE KIND = 'FOLLOW_UP' AND DUE_DATE <= %s::DATE",
                (as_of,),
            )
        return int(row["n"]) if row else 0

    def lab_is_pending_for(self, role: str, patient_id: str, lab_id: str) -> bool:
        """Is this the patient's latest lab (the one a review applies to)? Read under the caller's role."""
        with user_cursor(role) as cur:
            return (
                fetch_one(
                    cur,
                    "SELECT 1 AS OK FROM ANALYTICS.PATIENT_LAB_LATEST WHERE PATIENT_ID = %s AND LATEST_LAB_ID = %s",
                    (patient_id, lab_id),
                )
                is not None
            )

    def mark_reviewed(self, role: str, user_id: str, patient_id: str, lab_id: str) -> Row:
        """Insert the review once; repeating returns the first row (the table is insert-only)."""
        with user_cursor(role) as cur:
            existing = fetch_one(
                cur,
                "SELECT LAB_ID, PATIENT_ID, REVIEWED_AT FROM ANALYTICS.LAB_REVIEW WHERE LAB_ID = %s",
                (lab_id,),
            )
            if existing:
                return existing
            execute(
                cur,
                "INSERT INTO ANALYTICS.LAB_REVIEW (LAB_ID, PATIENT_ID, REVIEWED_BY, REVIEWED_AT) "
                "SELECT %s, %s, %s, SYSDATE()",
                (lab_id, patient_id, user_id),
            )
            row = fetch_one(
                cur,
                "SELECT LAB_ID, PATIENT_ID, REVIEWED_AT FROM ANALYTICS.LAB_REVIEW WHERE LAB_ID = %s",
                (lab_id,),
            )
        assert row is not None
        return row
