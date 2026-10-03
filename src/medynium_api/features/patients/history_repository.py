"""Timeline, claims and notes reads (same rules as repository.py: caller's role, None when not visible)."""

from datetime import date

from medynium_api.core.snowflake.queries import Row, fetch_all, fetch_one
from medynium_api.core.snowflake.role_session import user_cursor

TIMELINE_LIMIT = 500


class HistoryRepository:
    def timeline(
        self,
        role: str,
        patient_id: str,
        start: date | None,
        end: date | None,
        types: list[str] | None,
        as_of: str,
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
                f"ORDER BY EVENT_DATE DESC, EVENT_ID DESC LIMIT {TIMELINE_LIMIT}",
                params,
            )

    def claims(self, role: str, patient_id: str) -> dict[str, object] | None:
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
                "SELECT CLAIM_ID, ENCOUNTER_ID, SERVICE_DATE, SERVICE_TEXT, STATUS, BILLED_INR, APPROVED_INR "
                "FROM CLINICAL.CLAIM WHERE PATIENT_ID = %s ORDER BY SERVICE_DATE DESC, CLAIM_ID DESC LIMIT 200",
                (patient_id,),
            )
        return {"utilization": utilization or {}, "claims": claims}

    def notes(self, role: str, patient_id: str) -> list[Row] | None:
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
                "SELECT NOTE_ID, TITLE, NOTE_TYPE, NOTE_DATE, ENCOUNTER_ID FROM CLINICAL.CLINICAL_NOTE "
                "WHERE PATIENT_ID = %s ORDER BY NOTE_DATE DESC, NOTE_ID",
                (patient_id,),
            )

    def note(self, role: str, patient_id: str, note_id: str) -> Row | None:
        with user_cursor(role) as cur:
            return fetch_one(
                cur,
                "SELECT NOTE_ID, TITLE, NOTE_TYPE, NOTE_DATE, ENCOUNTER_ID, AUTHOR, BODY FROM CLINICAL.CLINICAL_NOTE "
                "WHERE PATIENT_ID = %s AND NOTE_ID = %s",
                (patient_id, note_id),
            )
