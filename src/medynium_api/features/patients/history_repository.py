"""Timeline, claims and notes reads (same rules as repository.py: caller's role, None when not visible)."""

from datetime import date

from medynium_api.core.pagination import like, order_clause
from medynium_api.core.snowflake.queries import Row, fetch_all, fetch_one
from medynium_api.core.snowflake.role_session import user_cursor

CLAIM_SORTS = {
    "date": "SERVICE_DATE",
    "billed": "BILLED_INR",
    "approved": "APPROVED_INR",
    "status": "STATUS",
}
NOTE_SORTS = {"date": "NOTE_DATE", "title": "TITLE"}


class HistoryRepository:
    def timeline(
        self,
        role: str,
        patient_id: str,
        start: date | None,
        end: date | None,
        types: list[str] | None,
        as_of: str,
        q: str | None,
        order: str,
        limit: int,
        offset: int,
    ) -> list[Row] | None:
        where = ["PATIENT_ID = %s", "EVENT_DATE <= %s::DATE"]
        params: list[object] = [patient_id, as_of]
        if start:
            where.append("EVENT_DATE >= %s")
            params.append(start)
        if end:
            where.append("EVENT_DATE <= %s")
            params.append(end)
        if types:
            where.append(f"EVENT_TYPE IN ({', '.join(['%s'] * len(types))})")
            params += types
        if q:
            where.append("(TITLE ILIKE %s OR SUMMARY ILIKE %s)")
            params += [like(q), like(q)]
        direction = "ASC" if order == "asc" else "DESC"
        with user_cursor(role) as cur:
            if not fetch_one(
                cur,
                "SELECT 1 AS OK FROM ANALYTICS.PATIENT_360 WHERE PATIENT_ID = %s",
                (patient_id,),
            ):
                return None
            return fetch_all(
                cur,
                "SELECT EVENT_ID, EVENT_DATE, EVENT_TYPE, TITLE, SUMMARY, RECORD_ID, RECORD_TABLE, ENCOUNTER_ID, "
                f"COUNT(*) OVER () AS TOTAL FROM ANALYTICS.PATIENT_TIMELINE WHERE {' AND '.join(where)} "
                f"ORDER BY EVENT_DATE {direction}, EVENT_ID {direction} LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )

    def claims(
        self,
        role: str,
        patient_id: str,
        status: str | None,
        start: date | None,
        end: date | None,
        sort: str | None,
        order: str,
        limit: int,
        offset: int,
    ) -> tuple[Row, list[Row]] | None:
        where = ["PATIENT_ID = %s"]
        params: list[object] = [patient_id]
        if status:
            where.append("STATUS = %s")
            params.append(status)
        if start:
            where.append("SERVICE_DATE >= %s")
            params.append(start)
        if end:
            where.append("SERVICE_DATE <= %s")
            params.append(end)
        order_by = order_clause(sort, order, CLAIM_SORTS, "date", "CLAIM_ID")
        with user_cursor(role) as cur:
            if not fetch_one(
                cur,
                "SELECT 1 AS OK FROM ANALYTICS.PATIENT_360 WHERE PATIENT_ID = %s",
                (patient_id,),
            ):
                return None
            utilization = fetch_one(
                cur,
                "SELECT OPD_VISITS, EMERGENCY_VISITS, HOSPITALIZATIONS, PROCEDURES, BILLED_INR, APPROVED_INR "
                "FROM ANALYTICS.UTILIZATION WHERE PATIENT_ID = %s",
                (patient_id,),
            )
            claims = fetch_all(
                cur,
                "SELECT CLAIM_ID, ENCOUNTER_ID, SERVICE_DATE, SERVICE_TEXT, STATUS, BILLED_INR, APPROVED_INR, "
                f"COUNT(*) OVER () AS TOTAL FROM CLINICAL.CLAIM WHERE {' AND '.join(where)} "
                f"ORDER BY {order_by} LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
        return utilization or {}, claims

    def notes(
        self,
        role: str,
        patient_id: str,
        q: str | None,
        note_type: str | None,
        sort: str | None,
        order: str,
        limit: int,
        offset: int,
    ) -> list[Row] | None:
        where = ["PATIENT_ID = %s", "NOT IS_ARCHIVED"]
        params: list[object] = [patient_id]
        if q:
            where.append("(TITLE ILIKE %s OR BODY ILIKE %s)")
            params += [like(q), like(q)]
        if note_type:
            where.append("NOTE_TYPE = %s")
            params.append(note_type)
        order_by = order_clause(sort, order, NOTE_SORTS, "date", "NOTE_ID")
        with user_cursor(role) as cur:
            if not fetch_one(
                cur,
                "SELECT 1 AS OK FROM ANALYTICS.PATIENT_360 WHERE PATIENT_ID = %s",
                (patient_id,),
            ):
                return None
            # CONTAINS_INJECTION is a test marker and is never selected.
            return fetch_all(
                cur,
                "SELECT NOTE_ID, TITLE, NOTE_TYPE, NOTE_DATE, ENCOUNTER_ID, COUNT(*) OVER () AS TOTAL "
                f"FROM CLINICAL.CLINICAL_NOTE WHERE {' AND '.join(where)} "
                f"ORDER BY {order_by} LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )

    def note(self, role: str, patient_id: str, note_id: str) -> Row | None:
        with user_cursor(role) as cur:
            return fetch_one(
                cur,
                "SELECT NOTE_ID, TITLE, NOTE_TYPE, NOTE_DATE, ENCOUNTER_ID, AUTHOR, BODY FROM CLINICAL.CLINICAL_NOTE "
                "WHERE PATIENT_ID = %s AND NOTE_ID = %s AND NOT IS_ARCHIVED",
                (patient_id, note_id),
            )
