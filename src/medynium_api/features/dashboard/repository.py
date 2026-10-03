"""Dashboard reads. All run under the caller's own role, so the row access policy scopes every widget."""

from medynium_api.core.ranking import order_by_sql
from medynium_api.core.snowflake.queries import Row, fetch_all, fetch_one
from medynium_api.core.snowflake.role_session import user_cursor


class DashboardRepository:
    def load(self, snowflake_role: str, as_of: str) -> dict[str, list[Row] | Row]:
        with user_cursor(snowflake_role) as cur:
            worklist = fetch_all(
                cur,
                "SELECT PATIENT_ID, FULL_NAME, AGE_YEARS, SEX, LAST_ENCOUNTER_DATE, LAST_ENCOUNTER_KIND, "
                "LAST_ENCOUNTER_LABEL, NEW_LAB_COUNT, HAS_NEW_MEDICATION_CHANGE, HAS_RECENT_EMERGENCY, "
                "HAS_NEW_DOCUMENT "
                "FROM ANALYTICS.DASHBOARD_WORKLIST WHERE FLAG_COUNT > 0 "
                f"ORDER BY {order_by_sql()} LIMIT 10",
            )
            labs = fetch_all(
                cur,
                "SELECT l.PATIENT_ID, w.FULL_NAME, l.SHORT_NAME, l.LATEST_VALUE, l.PREVIOUS_VALUE, l.UNIT, "
                "l.LATEST_AT::DATE AS D, l.ABNORMAL_FLAG "
                "FROM ANALYTICS.PATIENT_LAB_LATEST l JOIN ANALYTICS.DASHBOARD_WORKLIST w ON w.PATIENT_ID = l.PATIENT_ID "
                "WHERE l.IS_NEW_SINCE_LAST_VISIT "
                "ORDER BY IFF(l.ABNORMAL_FLAG IN ('LOW', 'HIGH'), 0, 1), l.LATEST_AT DESC, l.PATIENT_ID LIMIT 10",
            )
            meds = fetch_all(
                cur,
                "SELECT m.PATIENT_ID, w.FULL_NAME, m.DRUG_NAME, m.CHANGE_NOTE, m.START_DATE, m.LAST_CHANGE_DATE "
                "FROM ANALYTICS.CURRENT_MEDICATIONS m JOIN ANALYTICS.DASHBOARD_WORKLIST w ON w.PATIENT_ID = m.PATIENT_ID "
                "WHERE COALESCE(m.LAST_CHANGE_DATE, m.START_DATE) BETWEEN DATEADD('day', -60, %s::DATE) AND %s::DATE "
                "ORDER BY COALESCE(m.LAST_CHANGE_DATE, m.START_DATE) DESC, m.PATIENT_ID LIMIT 10",
                (as_of, as_of),
            )
            utilization = fetch_one(
                cur,
                "SELECT COUNT(*) AS PATIENTS, COALESCE(SUM(OPD_VISITS), 0) AS OPD, COALESCE(SUM(EMERGENCY_VISITS), 0) AS ED, "
                "COALESCE(SUM(HOSPITALIZATIONS), 0) AS HOSP, COALESCE(SUM(PROCEDURES), 0) AS PROC, "
                "COALESCE(SUM(APPROVED_INR), 0) AS APPROVED FROM ANALYTICS.UTILIZATION",
            )
        return {"worklist": worklist, "labs": labs, "meds": meds, "utilization": utilization or {}}
