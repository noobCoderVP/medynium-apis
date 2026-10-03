"""Saved views and visit briefs under the caller's role. Writes only happen after an approved preview."""

import json
from typing import Any

from medynium_api.core.snowflake.queries import Row, execute, fetch_all, fetch_one
from medynium_api.core.snowflake.role_session import user_cursor

COLUMNS = "VIEW_ID, KIND, PATIENT_ID, TITLE, CONTENT, APPROVED_AT, CREATED_AT"


class ViewRepository:
    def save(
        self,
        role: str,
        view_id: str,
        user_id: str,
        patient_id: str,
        kind: str,
        title: str,
        content: dict[str, Any],
    ) -> Row | None:
        with user_cursor(role) as cur:
            execute(
                cur,
                "INSERT INTO ANALYTICS.SAVED_VIEW (VIEW_ID, USER_ID, PATIENT_ID, KIND, TITLE, CONTENT, APPROVED_AT, "
                "CREATED_AT) SELECT %s, %s, %s, %s, %s, PARSE_JSON(%s), SYSDATE(), SYSDATE()",
                (view_id, user_id, patient_id, kind, title, json.dumps(content)),
            )
            return fetch_one(
                cur, f"SELECT {COLUMNS} FROM ANALYTICS.SAVED_VIEW WHERE VIEW_ID = %s", (view_id,)
            )

    def list_views(self, role: str, patient_id: str | None) -> list[Row]:
        with user_cursor(role) as cur:
            return fetch_all(
                cur,
                f"SELECT {COLUMNS} FROM ANALYTICS.SAVED_VIEW WHERE (%s IS NULL OR PATIENT_ID = %s) "
                "ORDER BY CREATED_AT DESC LIMIT 100",
                (patient_id, patient_id),
            )
