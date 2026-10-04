"""Patient reads. Every method runs under the caller's role and returns None when the patient is not visible,
so a denied patient and a missing one follow exactly the same path (SEC-05). No joins at request time beyond
small lookups: data comes from the ANALYTICS read models (NFR-11)."""

from datetime import date
from typing import Any

import structlog

from medynium_api.core.pagination import like, order_clause
from medynium_api.core.snowflake.queries import Row, fetch_all, fetch_one
from medynium_api.core.snowflake.role_session import service_cursor, user_cursor
from medynium_api.features.patients.filters import (
    FLAG_COLUMNS,
    LAB_SORTS,
    MEDICATION_SORTS,
    PATIENT_SORTS,
    PatientFilters,
)

log = structlog.get_logger()


def _visible(cur: Any, patient_id: str) -> Row | None:
    return fetch_one(
        cur,
        "SELECT PATIENT_ID, FULL_NAME, AGE_YEARS, SEX, CITY, ACTIVE_DIAGNOSES FROM ANALYTICS.PATIENT_360 "
        "WHERE PATIENT_ID = %s",
        (patient_id,),
    )


def active_allergies(cur: Any, patient_id: str) -> list[Row]:
    """Active allergies, worst first. Before `db.py apply 03` creates the table this returns none (and logs) rather
    than taking the whole patient page down."""
    try:
        return fetch_all(
            cur,
            "SELECT ALLERGY_ID, SUBSTANCE, REACTION, SEVERITY FROM CLINICAL.ALLERGY "
            "WHERE PATIENT_ID = %s AND IS_ACTIVE AND NOT IS_ARCHIVED "
            "ORDER BY DECODE(SEVERITY, 'SEVERE', 0, 'MODERATE', 1, 2), SUBSTANCE",
            (patient_id,),
        )
    except Exception as exc:
        log.warning("allergy_read_failed", error=type(exc).__name__)
        return []


class PatientRepository:
    def list_patients(
        self,
        role: str,
        filters: PatientFilters,
        limit: int,
        offset: int,
    ) -> tuple[list[Row], int]:
        where, params = ["TRUE"], []
        if filters.q:
            where.append(
                "(w.FULL_NAME ILIKE %s OR w.PATIENT_ID ILIKE %s OR ARRAY_TO_STRING(w.MAIN_DIAGNOSES, ' ') ILIKE %s)"
            )
            pattern = like(filters.q)
            params += [pattern, pattern, pattern]
        if filters.changed:
            where.append("w.FLAG_COUNT > 0")
        if filters.sex:
            where.append("UPPER(w.SEX) = %s")
            params.append(filters.sex.upper())
        if filters.kind:
            where.append("w.LAST_ENCOUNTER_KIND = %s")
            params.append(filters.kind)
        if filters.flag:
            where.append(FLAG_COLUMNS[filters.flag])
        order = order_clause(
            filters.sort, filters.order, PATIENT_SORTS, "last_encounter", "w.PATIENT_ID"
        )
        sql = (
            "SELECT w.PATIENT_ID, w.FULL_NAME, w.AGE_YEARS, w.SEX, w.MAIN_DIAGNOSES, w.LAST_ENCOUNTER_DATE, "
            "w.LAST_ENCOUNTER_KIND, w.LAST_ENCOUNTER_LABEL, w.NEW_LAB_COUNT, w.HAS_NEW_MEDICATION_CHANGE, "
            "w.HAS_RECENT_EMERGENCY, w.HAS_NEW_DOCUMENT, COUNT(*) OVER () AS TOTAL "
            f"FROM ANALYTICS.DASHBOARD_WORKLIST w WHERE {' AND '.join(where)} "
            f"ORDER BY {order} LIMIT %s OFFSET %s"
        )
        with user_cursor(role) as cur:
            rows = fetch_all(cur, sql, [*params, limit, offset])
        return rows, int(rows[0]["total"]) if rows else 0

    @staticmethod
    def sender_name(user_id: str) -> str | None:
        with service_cursor() as cur:
            row = fetch_one(
                cur, "SELECT DISPLAY_NAME FROM SECURITY.APP_USER WHERE USER_ID = %s", (user_id,)
            )
        return str(row["display_name"]) if row else None

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
            allergies = active_allergies(cur, patient_id)
        return {
            "allergies": allergies,
            "patient": patient,
            "meds": meds,
            "labs": labs,
            "events": events,
            "utilization": utilization or {},
        }

    def medications(
        self,
        role: str,
        patient_id: str,
        active_only: bool,
        q: str | None,
        sort: str | None,
        order: str,
        limit: int,
        offset: int,
    ) -> tuple[list[Row], int] | None:
        where = ["m.PATIENT_ID = %s", "NOT m.IS_ARCHIVED", "(NOT %s OR m.IS_ACTIVE)"]
        params: list[object] = [patient_id, active_only]
        if q:
            where.append("(m.DRUG_NAME ILIKE %s OR m.DESCRIPTION ILIKE %s)")
            params += [like(q), like(q)]
        order_by = order_clause(sort, order, MEDICATION_SORTS, "started", "m.MEDICATION_ID")
        with user_cursor(role) as cur:
            if not _visible(cur, patient_id):
                return None
            rows = fetch_all(
                cur,
                "SELECT m.MEDICATION_ID, m.DRUG_NAME, m.DESCRIPTION, m.DOSE_TEXT, m.STRENGTH_TEXT, m.START_DATE, "
                "m.STOP_DATE, m.LAST_CHANGE_DATE, m.CHANGE_NOTE, m.DRUG_ID IS NOT NULL AS IN_KB, b.BRANDS, "
                "COUNT(*) OVER () AS TOTAL "
                "FROM CLINICAL.MEDICATION m LEFT JOIN "
                "(SELECT DRUG_ID, ARRAY_SLICE(ARRAY_AGG(DISTINCT NAME_TEXT), 0, 3) AS BRANDS "
                " FROM KNOWLEDGE.DRUG_NAME_MAP WHERE NAME_KIND = 'INDIAN_BRAND' GROUP BY DRUG_ID) b "
                f"ON b.DRUG_ID = m.DRUG_ID WHERE {' AND '.join(where)} "
                f"ORDER BY {order_by} LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
        return rows, int(rows[0]["total"]) if rows else 0

    @staticmethod
    def _medications(cur: Any, patient_id: str, active_only: bool) -> list[Row]:
        return fetch_all(
            cur,
            "SELECT m.MEDICATION_ID, m.DRUG_NAME, m.DESCRIPTION, m.DOSE_TEXT, m.STRENGTH_TEXT, m.START_DATE, "
            "m.STOP_DATE, m.LAST_CHANGE_DATE, m.CHANGE_NOTE, m.DRUG_ID IS NOT NULL AS IN_KB, "
            "b.BRANDS "
            "FROM CLINICAL.MEDICATION m LEFT JOIN "
            "(SELECT DRUG_ID, ARRAY_SLICE(ARRAY_AGG(DISTINCT NAME_TEXT), 0, 3) AS BRANDS "
            " FROM KNOWLEDGE.DRUG_NAME_MAP WHERE NAME_KIND = 'INDIAN_BRAND' GROUP BY DRUG_ID) b "
            "ON b.DRUG_ID = m.DRUG_ID WHERE m.PATIENT_ID = %s AND NOT m.IS_ARCHIVED AND (NOT %s OR m.IS_ACTIVE) "
            "ORDER BY m.IS_ACTIVE DESC, m.START_DATE DESC, m.MEDICATION_ID LIMIT 200",
            (patient_id, active_only),
        )

    def labs(
        self,
        role: str,
        patient_id: str,
        q: str | None,
        flag: str | None,
        sort: str | None,
        order: str,
        limit: int,
        offset: int,
    ) -> tuple[list[Row], int] | None:
        where = ["PATIENT_ID = %s"]
        params: list[object] = [patient_id]
        if q:
            where.append("(TEST_NAME ILIKE %s OR SHORT_NAME ILIKE %s)")
            params += [like(q), like(q)]
        if flag == "abnormal":
            where.append("ABNORMAL_FLAG IN ('LOW', 'HIGH')")
        elif flag in ("LOW", "HIGH"):
            where.append("ABNORMAL_FLAG = %s")
            params.append(flag)
        elif flag == "NORMAL":
            where.append("COALESCE(ABNORMAL_FLAG, 'NORMAL') NOT IN ('LOW', 'HIGH')")
        order_by = order_clause(sort, order, LAB_SORTS, "test", "LATEST_LAB_ID")
        with user_cursor(role) as cur:
            if not _visible(cur, patient_id):
                return None
            rows = fetch_all(
                cur,
                "SELECT LATEST_LAB_ID, SHORT_NAME, TEST_NAME, LOINC_CODE, LATEST_VALUE, UNIT, LATEST_AT::DATE AS D, "
                "PREVIOUS_VALUE, PREVIOUS_AT::DATE AS PD, REF_LOW, REF_HIGH, ABNORMAL_FLAG, COUNT(*) OVER () AS TOTAL "
                f"FROM ANALYTICS.PATIENT_LAB_LATEST WHERE {' AND '.join(where)} "
                f"ORDER BY {order_by} LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
        return rows, int(rows[0]["total"]) if rows else 0

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
                "AND LOINC_CODE = %s AND VALUE_NUM IS NOT NULL AND OBSERVED_AT::DATE <= %s::DATE AND NOT IS_ARCHIVED "
                "ORDER BY OBSERVED_AT, LAB_ID",
                (patient_id, ref["loinc_code"], as_of),
            )
        return {"known": True, "ref": ref, "points": points}


def as_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None
