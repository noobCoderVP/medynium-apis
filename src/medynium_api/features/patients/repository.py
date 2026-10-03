"""Patient reads. Every method runs under the caller's role and returns None when the patient is not visible,
so a denied patient and a missing one follow exactly the same path (SEC-05). No joins at request time beyond
small lookups: data comes from the ANALYTICS read models (NFR-11)."""

from datetime import date
from typing import Any

from medynium_api.core.snowflake.queries import Row, fetch_all, fetch_one
from medynium_api.core.snowflake.role_session import user_cursor


def _visible(cur: Any, patient_id: str) -> Row | None:
    return fetch_one(
        cur,
        "SELECT PATIENT_ID, FULL_NAME, AGE_YEARS, SEX, CITY, ACTIVE_DIAGNOSES FROM ANALYTICS.PATIENT_360 "
        "WHERE PATIENT_ID = %s",
        (patient_id,),
    )


class PatientRepository:
    def list_patients(
        self, role: str, q: str | None, changed: bool, limit: int, offset: int
    ) -> tuple[list[Row], int]:
        where, params = ["TRUE"], []
        if q:
            where.append(
                "(w.FULL_NAME ILIKE %s OR w.PATIENT_ID ILIKE %s OR ARRAY_TO_STRING(w.MAIN_DIAGNOSES, ' ') ILIKE %s)"
            )
            params += [f"%{q}%", f"%{q}%", f"%{q}%"]
        if changed:
            where.append("w.FLAG_COUNT > 0")
        sql = (
            "SELECT w.PATIENT_ID, w.FULL_NAME, w.AGE_YEARS, w.SEX, w.MAIN_DIAGNOSES, w.LAST_ENCOUNTER_DATE, "
            "w.LAST_ENCOUNTER_KIND, w.LAST_ENCOUNTER_LABEL, w.NEW_LAB_COUNT, w.HAS_NEW_MEDICATION_CHANGE, "
            "w.HAS_RECENT_EMERGENCY, w.HAS_NEW_DOCUMENT, COUNT(*) OVER () AS TOTAL "
            f"FROM ANALYTICS.DASHBOARD_WORKLIST w WHERE {' AND '.join(where)} "
            "ORDER BY w.LAST_ENCOUNTER_DATE DESC NULLS LAST, w.PATIENT_ID LIMIT %s OFFSET %s"
        )
        with user_cursor(role) as cur:
            rows = fetch_all(cur, sql, [*params, limit, offset])
        return rows, int(rows[0]["total"]) if rows else 0

    def overview(self, role: str, patient_id: str, as_of: str) -> Row | None:
        with user_cursor(role) as cur:
            patient = _visible(cur, patient_id)
            if not patient:
                return None
            meds = self._medications(cur, patient_id, active_only=True)
            labs = fetch_all(
                cur,
                "SELECT LATEST_LAB_ID, SHORT_NAME, TEST_NAME, LOINC_CODE, LATEST_VALUE, UNIT, LATEST_AT::DATE AS D, "
                "PREVIOUS_VALUE, PREVIOUS_AT::DATE AS PD, REF_LOW, REF_HIGH, ABNORMAL_FLAG "
                "FROM ANALYTICS.PATIENT_LAB_LATEST WHERE PATIENT_ID = %s "
                "ORDER BY IFF(ABNORMAL_FLAG IN ('LOW', 'HIGH'), 0, 1), SHORT_NAME",
                (patient_id,),
            )
            events = fetch_all(
                cur,
                "SELECT EVENT_ID, EVENT_DATE, EVENT_TYPE, TITLE, SUMMARY, RECORD_ID, RECORD_TABLE, ENCOUNTER_ID "
                "FROM ANALYTICS.PATIENT_TIMELINE WHERE PATIENT_ID = %s ORDER BY EVENT_DATE DESC, EVENT_ID DESC LIMIT 6",
                (patient_id,),
            )
            utilization = fetch_one(
                cur,
                "SELECT OPD_VISITS, EMERGENCY_VISITS, HOSPITALIZATIONS, PROCEDURES, BILLED_INR, APPROVED_INR "
                "FROM ANALYTICS.UTILIZATION WHERE PATIENT_ID = %s",
                (patient_id,),
            )
        return {
            "patient": patient,
            "meds": meds,
            "labs": labs,
            "events": events,
            "utilization": utilization or {},
        }

    def medications(self, role: str, patient_id: str, active_only: bool) -> list[Row] | None:
        with user_cursor(role) as cur:
            if not _visible(cur, patient_id):
                return None
            return self._medications(cur, patient_id, active_only)

    @staticmethod
    def _medications(cur: Any, patient_id: str, active_only: bool) -> list[Row]:
        return fetch_all(
            cur,
            "SELECT m.MEDICATION_ID, m.DRUG_NAME, m.DESCRIPTION, m.DOSE_TEXT, m.STRENGTH_TEXT, m.START_DATE, "
            "m.STOP_DATE, m.LAST_CHANGE_DATE, m.CHANGE_NOTE, m.DRUG_ID IS NOT NULL AS IN_KB, "
            "(SELECT ARRAY_SLICE(ARRAY_AGG(DISTINCT n.NAME_TEXT), 0, 3) FROM KNOWLEDGE.DRUG_NAME_MAP n "
            " WHERE n.DRUG_ID = m.DRUG_ID AND n.NAME_KIND = 'INDIAN_BRAND') AS BRANDS "
            "FROM CLINICAL.MEDICATION m WHERE m.PATIENT_ID = %s AND (NOT %s OR m.IS_ACTIVE) "
            "ORDER BY m.IS_ACTIVE DESC, m.START_DATE DESC, m.MEDICATION_ID LIMIT 200",
            (patient_id, active_only),
        )

    def labs(self, role: str, patient_id: str, q: str | None) -> list[Row] | None:
        with user_cursor(role) as cur:
            if not _visible(cur, patient_id):
                return None
            return fetch_all(
                cur,
                "SELECT LATEST_LAB_ID, SHORT_NAME, TEST_NAME, LOINC_CODE, LATEST_VALUE, UNIT, LATEST_AT::DATE AS D, "
                "PREVIOUS_VALUE, PREVIOUS_AT::DATE AS PD, REF_LOW, REF_HIGH, ABNORMAL_FLAG "
                "FROM ANALYTICS.PATIENT_LAB_LATEST WHERE PATIENT_ID = %s AND (%s IS NULL OR TEST_NAME ILIKE %s "
                "OR SHORT_NAME ILIKE %s) ORDER BY SHORT_NAME",
                (patient_id, q, f"%{q or ''}%", f"%{q or ''}%"),
            )

    def lab_trend(self, role: str, patient_id: str, code: str, as_of: str) -> dict[str, Any] | None:
        """None if the patient is not visible; {"known": False} for an unknown test code."""
        with user_cursor(role) as cur:
            if not _visible(cur, patient_id):
                return None
            ref = fetch_one(
                cur,
                "SELECT LOINC_CODE, SHORT_NAME, TEST_NAME, UNIT, REF_LOW, REF_HIGH FROM CLINICAL.LAB_REFERENCE "
                "WHERE LOINC_CODE = %s OR LOWER(SHORT_NAME) = LOWER(%s)",
                (code, code),
            )
            if not ref:
                return {"known": False}
            points = fetch_all(
                cur,
                "SELECT LAB_ID, OBSERVED_AT::DATE AS D, VALUE_NUM FROM CLINICAL.LAB_RESULT WHERE PATIENT_ID = %s "
                "AND LOINC_CODE = %s AND VALUE_NUM IS NOT NULL AND OBSERVED_AT::DATE <= %s::DATE "
                "ORDER BY OBSERVED_AT, LAB_ID",
                (patient_id, ref["loinc_code"], as_of),
            )
        return {"known": True, "ref": ref, "points": points}


def as_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None
