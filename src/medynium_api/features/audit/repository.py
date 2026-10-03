"""The caller's own audit rows. The OWN_RAP policy restricts COPILOT_AUDIT to the caller's USER_ID."""

import datetime as dt

from medynium_api.core.snowflake.queries import Row, fetch_all
from medynium_api.core.snowflake.role_session import user_cursor


class AuditRepository:
    def list_entries(
        self,
        role: str,
        patient_id: str | None,
        start: dt.date | None,
        end: dt.date | None,
        action: str | None,
        outcome: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Row], int]:
        where, params = ["TRUE"], []
        for clause, value in (
            ("PATIENT_ID = %s", patient_id),
            ("OCCURRED_AT::DATE >= %s", start),
            ("OCCURRED_AT::DATE <= %s", end),
            ("ACTION = %s", action),
            ("OUTCOME = %s", outcome),
        ):
            if value is not None:
                where.append(clause)
                params.append(value)
        with user_cursor(role) as cur:
            rows = fetch_all(
                cur,
                "SELECT AUDIT_ID, OCCURRED_AT, VIA, ACTION, ROUTE, MODEL, CONFIDENCE, COST_NOTE, PATIENT_ID, QUESTION, "
                "ANSWER_ID, PATIENT_EVIDENCE_IDS, DOCUMENT_IDS, STEPS, OUTCOME, COUNT(*) OVER () AS TOTAL "
                f"FROM ANALYTICS.COPILOT_AUDIT WHERE {' AND '.join(where)} ORDER BY OCCURRED_AT DESC, AUDIT_ID DESC "
                "LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
        return rows, int(rows[0]["total"]) if rows else 0
