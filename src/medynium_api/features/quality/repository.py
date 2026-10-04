"""Stored golden runs, read with the admin's own role (ANALYTICS.GOLDEN_RUN / GOLDEN_RESULT hold no patient data)."""

from medynium_api.core.snowflake.queries import Row, fetch_all
from medynium_api.core.snowflake.role_session import user_cursor


class QualityRepository:
    def runs(self, role: str, limit: int) -> list[Row]:
        with user_cursor(role) as cur:
            return fetch_all(
                cur,
                "SELECT RUN_ID, STARTED_AT, FINISHED_AT, STATUS, GOLDEN_TOTAL, GOLDEN_PASSED "
                "FROM ANALYTICS.GOLDEN_RUN ORDER BY STARTED_AT DESC LIMIT %s",
                (limit,),
            )

    def results(self, role: str, run_id: str) -> list[Row]:
        with user_cursor(role) as cur:
            return fetch_all(
                cur,
                "SELECT SEQ, SET_NAME, QUESTION, EXPECTED, ROUTE_ACTUAL, RESULT "
                "FROM ANALYTICS.GOLDEN_RESULT WHERE RUN_ID = %s ORDER BY SEQ",
                (run_id,),
            )
