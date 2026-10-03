"""Findings under the caller's role: the entitled-patient policy decides what is visible. Names and colleagues come
from the service role, which can read the account tables but no patient table."""

import datetime as dt

from medynium_api.core.snowflake.queries import Row, execute, fetch_all, fetch_one, json_value
from medynium_api.core.snowflake.role_session import service_cursor, user_cursor

COLUMNS = (
    "FINDING_ID, PATIENT_ID, ANSWER_ID, CONSIDERATION_ID, SUMMARY, STATUS, REASON, FOLLOW_UP_ON, "
    "ASSIGNED_TO, CREATED_BY, CREATED_AT, UPDATED_AT"
)
BY_ID = f"SELECT {COLUMNS} FROM ANALYTICS.FINDING WHERE FINDING_ID = %s"


class FindingRepository:
    def list_findings(self, role: str, patient_id: str) -> list[Row]:
        with user_cursor(role) as cur:
            return fetch_all(
                cur,
                f"SELECT {COLUMNS} FROM ANALYTICS.FINDING WHERE PATIENT_ID = %s "
                "ORDER BY IFF(STATUS IN ('NEW', 'FLAGGED', 'ESCALATED'), 0, 1), CREATED_AT DESC",
                (patient_id,),
            )

    def get(self, role: str, finding_id: str) -> Row | None:
        with user_cursor(role) as cur:
            return fetch_one(cur, BY_ID, (finding_id,))

    def statement(
        self, role: str, patient_id: str, answer_id: str, consideration_id: str
    ) -> str | None:
        """The statement text from one of the caller's own answers about this patient, or None."""
        with user_cursor(role) as cur:
            row = fetch_one(
                cur,
                "SELECT ANSWER_JSON FROM ANALYTICS.ANSWER WHERE ANSWER_ID = %s AND PATIENT_ID = %s",
                (answer_id, patient_id),
            )
        answer = json_value(row["answer_json"]) if row else None
        for item in (answer or {}).get("considerations", []):
            if item.get("id") == consideration_id:
                return str(item.get("text", ""))[:700]
        return None

    def existing(
        self, role: str, patient_id: str, answer_id: str, consideration_id: str
    ) -> Row | None:
        with user_cursor(role) as cur:
            return fetch_one(
                cur,
                f"SELECT {COLUMNS} FROM ANALYTICS.FINDING WHERE PATIENT_ID = %s AND ANSWER_ID = %s "
                "AND CONSIDERATION_ID = %s",
                (patient_id, answer_id, consideration_id),
            )

    def create(
        self,
        role: str,
        finding_id: str,
        patient_id: str,
        answer_id: str,
        consideration_id: str,
        summary: str,
        user_id: str,
    ) -> Row | None:
        with user_cursor(role) as cur:
            execute(
                cur,
                "INSERT INTO ANALYTICS.FINDING (FINDING_ID, PATIENT_ID, ANSWER_ID, CONSIDERATION_ID, SUMMARY, "
                "STATUS, CREATED_BY, CREATED_AT) SELECT %s, %s, %s, %s, %s, 'NEW', %s, SYSDATE()",
                (finding_id, patient_id, answer_id, consideration_id, summary, user_id),
            )
            return fetch_one(cur, BY_ID, (finding_id,))

    def update(
        self,
        role: str,
        finding_id: str,
        status: str,
        reason: str | None,
        follow_up_on: dt.date | None,
        assigned_to: str | None,
        user_id: str,
    ) -> Row | None:
        with user_cursor(role) as cur:
            execute(
                cur,
                "UPDATE ANALYTICS.FINDING SET STATUS = %s, REASON = %s, FOLLOW_UP_ON = %s, ASSIGNED_TO = %s, "
                "UPDATED_BY = %s, UPDATED_AT = SYSDATE() WHERE FINDING_ID = %s",
                (status, reason, follow_up_on, assigned_to, user_id, finding_id),
            )
            return fetch_one(cur, BY_ID, (finding_id,))

    def names(self, user_ids: set[str]) -> dict[str, str]:
        if not user_ids:
            return {}
        marks = ", ".join(["%s"] * len(user_ids))
        with service_cursor() as cur:
            rows = fetch_all(
                cur,
                f"SELECT USER_ID, DISPLAY_NAME FROM SECURITY.APP_USER WHERE USER_ID IN ({marks})",
                tuple(user_ids),
            )
        return {r["user_id"]: r["display_name"] for r in rows}

    def colleagues(self, patient_id: str) -> list[Row]:
        """Active users who currently have this patient."""
        with service_cursor() as cur:
            return fetch_all(
                cur,
                "SELECT u.USER_ID, u.DISPLAY_NAME, u.ROLE_CODE FROM SECURITY.PATIENT_ENTITLEMENT e "
                "JOIN SECURITY.APP_USER u ON u.USER_ID = e.USER_ID "
                "WHERE e.PATIENT_ID = %s AND e.REVOKED_AT IS NULL AND u.STATUS = 'ACTIVE' "
                "ORDER BY u.DISPLAY_NAME",
                (patient_id,),
            )
