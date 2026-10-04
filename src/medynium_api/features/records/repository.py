"""Writes go through the INTAKE procedures under the service role, which pass the verified actor's user id; reads run
under the caller's own role so the row access policy decides what is visible. The only SQL that changes CLINICAL is
inside Snowflake (snowflake/36_intake_procedures.sql); nothing here builds an INSERT or UPDATE."""

import json
from typing import Any

from medynium_api.core.snowflake.queries import Row, fetch_all, fetch_one, json_value
from medynium_api.core.snowflake.role_session import service_cursor, user_cursor

# entity -> (table, key column, fields shown to the caller, order). Fixed lists: never built from request data.
READ: dict[str, tuple[str, str, tuple[str, ...], str]] = {
    "DIAGNOSIS": (
        "CLINICAL.DIAGNOSIS", "DIAGNOSIS_ID",
        ("DESCRIPTION", "CODE", "CODE_SYSTEM", "ONSET_DATE", "RESOLVED_DATE", "IS_ACTIVE"),
        "IS_ACTIVE DESC, ONSET_DATE DESC NULLS LAST",
    ),
    "MEDICATION": (
        "CLINICAL.MEDICATION", "MEDICATION_ID",
        ("DESCRIPTION", "DRUG_NAME", "DRUG_ID", "STRENGTH_TEXT", "DOSE_TEXT", "START_DATE", "STOP_DATE",
         "IS_ACTIVE", "LAST_CHANGE_DATE", "CHANGE_NOTE", "REASON_DESCRIPTION"),
        "IS_ACTIVE DESC, START_DATE DESC NULLS LAST",
    ),
    "ALLERGY": (
        "CLINICAL.ALLERGY", "ALLERGY_ID",
        ("SUBSTANCE", "REACTION", "SEVERITY", "IS_ACTIVE", "RECORDED_ON"),
        "IS_ACTIVE DESC, SUBSTANCE",
    ),
    "LAB_RESULT": (
        "CLINICAL.LAB_RESULT", "LAB_ID",
        ("LOINC_CODE", "TEST_NAME", "VALUE_NUM", "UNIT", "REF_LOW", "REF_HIGH", "ABNORMAL_FLAG", "OBSERVED_AT"),
        "OBSERVED_AT DESC",
    ),
    "CLINICAL_NOTE": (
        "CLINICAL.CLINICAL_NOTE", "NOTE_ID",
        ("TITLE", "NOTE_TYPE", "NOTE_DATE", "AUTHOR", "BODY"),
        "NOTE_DATE DESC",
    ),
    "ENCOUNTER": (
        "CLINICAL.ENCOUNTER", "ENCOUNTER_ID",
        ("STARTED_AT", "ENDED_AT", "VISIT_KIND", "DESCRIPTION", "REASON_DESCRIPTION"),
        "STARTED_AT DESC",
    ),
}  # fmt: skip
MAX_ROWS = 200


class RecordRepository:
    # Writes ---------------------------------------------------------------------------------------------------
    def register_patient(
        self, actor_id: str, payload: dict[str, Any], key: str | None, as_of: str
    ) -> dict[str, Any]:
        with service_cursor() as cur:
            cur.execute(
                "CALL INTAKE.REGISTER_PATIENT(%s, %s, %s, %s::DATE)",
                (actor_id, json.dumps(payload), key, as_of),
            )
            return _result(cur)

    def write(
        self,
        actor_id: str,
        entity: str,
        op: str,
        patient_id: str,
        record_id: str | None,
        version: int | None,
        payload: dict[str, Any] | None,
        key: str | None,
        reason: str | None,
        as_of: str,
    ) -> dict[str, Any]:
        with service_cursor() as cur:
            cur.execute(
                "CALL INTAKE.WRITE_RECORD(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::DATE, %s)",
                (actor_id, entity, op, patient_id, record_id, version,
                 json.dumps(payload) if payload is not None else None, key, reason, as_of, "MANUAL"),
            )  # fmt: skip
            return _result(cur)

    # Reads, under the caller's role -------------------------------------------------------------------------
    def find_duplicate(self, role: str, full_name: str, birth_date: str) -> bool:
        with user_cursor(role) as cur:
            row = fetch_one(
                cur,
                "SELECT PATIENT_ID FROM CLINICAL.PATIENT WHERE LOWER(FULL_NAME) = LOWER(%s) "
                "AND BIRTH_DATE = %s::DATE AND NOT IS_ARCHIVED LIMIT 1",
                (full_name, birth_date),
            )
        return row is not None

    def list_records(
        self, role: str, patient_id: str, entity: str, include_archived: bool
    ) -> list[Row]:
        table, key, fields, order = READ[entity]
        where = "PATIENT_ID = %s" + ("" if include_archived else " AND NOT IS_ARCHIVED")
        with user_cursor(role) as cur:
            return fetch_all(
                cur,
                f"SELECT {key} AS RECORD_ID, VERSION, IS_ARCHIVED, UPDATED_AT, {', '.join(fields)} "
                f"FROM {table} WHERE {where} ORDER BY {order} LIMIT {MAX_ROWS}",
                (patient_id,),
            )

    def get_record(self, role: str, patient_id: str, entity: str, record_id: str) -> Row | None:
        table, key, fields, _ = READ[entity]
        with user_cursor(role) as cur:
            return fetch_one(
                cur,
                f"SELECT {key} AS RECORD_ID, VERSION, IS_ARCHIVED, UPDATED_AT, {', '.join(fields)} "
                f"FROM {table} WHERE PATIENT_ID = %s AND {key} = %s",
                (patient_id, record_id),
            )

    def history(self, role: str, patient_id: str, limit: int) -> list[Row]:
        with user_cursor(role) as cur:
            return fetch_all(
                cur,
                "SELECT AT, ACTOR_ID, ENTITY, RECORD_ID, OP, REASON, BEFORE_JSON, AFTER_JSON "
                "FROM CLINICAL.RECORD_HISTORY WHERE PATIENT_ID = %s ORDER BY AT DESC, HISTORY_ID LIMIT %s",
                (patient_id, limit),
            )

    def archived_patients(self, role: str) -> list[Row]:
        with user_cursor(role) as cur:
            return fetch_all(
                cur,
                "SELECT PATIENT_ID, FULL_NAME, VERSION, ARCHIVED_AT FROM CLINICAL.PATIENT WHERE IS_ARCHIVED "
                "ORDER BY ARCHIVED_AT DESC NULLS LAST LIMIT 200",
            )

    @staticmethod
    def names(user_ids: set[str]) -> dict[str, str]:
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


def _result(cur: Any) -> dict[str, Any]:
    value = json_value(next(iter(cur.fetchone().values())))
    return value if isinstance(value, dict) else {"ok": False, "error": "invalid"}
