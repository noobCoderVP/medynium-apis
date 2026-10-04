"""Reports: files in a private stage, state in tables, every change through an INTAKE procedure called as the service
role with the verified actor's id. Reads that show a person their own patient's reports run under that person's role, so
the entitled-patient policy decides what they see. Files are only ever read here, after the service has checked
entitlement; no URL to a file is ever handed out."""

import io
import json
import tempfile
from pathlib import Path
from typing import Any

from medynium_api.core.snowflake.queries import Row, fetch_all, fetch_one, json_value
from medynium_api.core.snowflake.role_session import service_cursor, user_cursor

STAGE = "@INTAKE.REPORT_STAGE"
SUMMARY = (
    "REPORT_ID, PATIENT_ID, FILENAME, MIME_TYPE, SIZE_BYTES, PAGE_COUNT, STATUS, STATUS_DETAIL, UPLOADED_BY, "
    "UPLOADED_AT, EXTRACTED_AT, NAME_ON_REPORT, IDENTITY_STATUS, IDENTITY_CONFIRMED_BY, ROWS_KEPT, ROWS_DROPPED, "
    "(SELECT COUNT(*) FROM CLINICAL.REPORT_ROW w WHERE w.REPORT_ID = r.REPORT_ID AND w.STATUS IN "
    "('PENDING', 'ACCEPTED', 'EDITED')) AS ROWS_WAITING"
)


def _call(sql: str, args: tuple[Any, ...]) -> dict[str, Any]:
    with service_cursor() as cur:
        cur.execute(sql, args)
        value = json_value(next(iter(cur.fetchone().values())))
    return value if isinstance(value, dict) else {"ok": False, "error": "invalid"}


class ReportRepository:
    # Files ----------------------------------------------------------------------------------------------------
    def put_file(self, patient_id: str, sha: str, extension: str, data: bytes) -> str:
        """Store a file under <patient>/<sha>.<ext>. Both parts are produced by code (validated id, hex digest)."""
        directory = f"{patient_id}/"
        with service_cursor() as cur:
            cur.execute(
                f"PUT file://{sha}.{extension} {STAGE}/{directory} AUTO_COMPRESS=FALSE OVERWRITE=TRUE",
                file_stream=io.BytesIO(data),
            )
        return f"{directory}{sha}.{extension}"

    def get_file(self, stage_path: str) -> bytes:
        with tempfile.TemporaryDirectory() as tmp, service_cursor() as cur:
            cur.execute(f"GET {STAGE}/{stage_path} file://{Path(tmp).as_posix()}/")
            cur.fetchall()
            return next(Path(tmp).iterdir()).read_bytes()

    # Procedures (service role, actor passed in) ---------------------------------------------------------------
    def create_report(
        self, actor: str, patient_id: str, filename: str, mime: str, size: int, sha: str, path: str
    ) -> dict[str, Any]:
        return _call(
            "CALL INTAKE.CREATE_REPORT(%s, %s, %s, %s, %s, %s, %s)",
            (actor, patient_id, filename, mime, size, sha, path),
        )

    def parse_report(self, report_id: str, max_pages: int) -> dict[str, Any]:
        return _call("CALL INTAKE.PARSE_REPORT(%s, %s)", (report_id, max_pages))

    def report_pages(self, report_id: str) -> dict[str, Any]:
        return _call("CALL INTAKE.REPORT_PAGES(%s)", (report_id,))

    def stage_rows(
        self, report_id: str, rows: list[dict[str, Any]], meta: dict[str, Any]
    ) -> dict[str, Any]:
        return _call(
            "CALL INTAKE.STAGE_ROWS(%s, %s, %s)", (report_id, json.dumps(rows), json.dumps(meta))
        )

    def fail_report(self, report_id: str, detail: str) -> None:
        with service_cursor() as cur:
            cur.execute("CALL INTAKE.FAIL_REPORT(%s, %s)", (report_id, detail))

    def decide_row(
        self, actor: str, patient_id: str, row_id: str, decision: str, version: int,
        fields: dict[str, Any] | None, collected_at: str | None, time_known: bool, flags: list[str],
    ) -> dict[str, Any]:  # fmt: skip
        return _call(
            "CALL INTAKE.DECIDE_ROW(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (actor, patient_id, row_id, decision, version, json.dumps(fields) if fields is not None else None,
             collected_at, time_known, json.dumps(flags)),
        )  # fmt: skip

    def begin_approval(
        self, actor: str, patient_id: str, report_id: str, confirm: bool
    ) -> dict[str, Any]:
        return _call(
            "CALL INTAKE.BEGIN_APPROVAL(%s, %s, %s, %s)", (actor, patient_id, report_id, confirm)
        )

    def finish_report(
        self, actor: str, patient_id: str, report_id: str, results: list[dict[str, str]]
    ) -> dict[str, Any]:
        return _call(
            "CALL INTAKE.FINISH_REPORT(%s, %s, %s, %s)",
            (actor, patient_id, report_id, json.dumps(results)),
        )

    def reject_report(self, actor: str, patient_id: str, report_id: str) -> dict[str, Any]:
        return _call("CALL INTAKE.REJECT_REPORT(%s, %s, %s)", (actor, patient_id, report_id))

    def stuck_reports(self, age_seconds: int) -> list[tuple[str, str]]:
        with service_cursor() as cur:
            cur.execute("CALL INTAKE.STUCK_REPORTS(%s)", (age_seconds,))
            value = json_value(next(iter(cur.fetchone().values())))
        return (
            [(str(v["report_id"]), str(v["uploaded_by"])) for v in value]
            if isinstance(value, list)
            else []
        )

    def write_record(
        self,
        actor: str,
        entity: str,
        patient_id: str,
        payload: dict[str, Any],
        key: str,
        source: str,
        as_of: str,
    ) -> dict[str, Any]:
        """One approved row becomes one clinical record through the same procedure the forms use."""
        return _call(
            "CALL INTAKE.WRITE_RECORD(%s, %s, 'CREATE', %s, NULL, NULL, %s, %s, NULL, %s::DATE, %s)",
            (actor, entity, patient_id, json.dumps(payload), key, as_of, source),
        )

    # Reads, under the caller's role ----------------------------------------------------------------------------
    def list_reports(self, role: str, patient_id: str) -> list[Row]:
        with user_cursor(role) as cur:
            return fetch_all(
                cur,
                f"SELECT {SUMMARY} FROM CLINICAL.REPORT r WHERE PATIENT_ID = %s ORDER BY UPLOADED_AT DESC LIMIT 100",
                (patient_id,),
            )

    def get_report(self, role: str, patient_id: str, report_id: str) -> Row | None:
        with user_cursor(role) as cur:
            return fetch_one(
                cur,
                f"SELECT {SUMMARY} FROM CLINICAL.REPORT r WHERE PATIENT_ID = %s AND REPORT_ID = %s",
                (patient_id, report_id),
            )

    def file_info(self, role: str, patient_id: str, report_id: str) -> Row | None:
        with user_cursor(role) as cur:
            return fetch_one(
                cur,
                "SELECT STAGE_PATH, MIME_TYPE, FILENAME FROM CLINICAL.REPORT WHERE PATIENT_ID = %s AND REPORT_ID = %s",
                (patient_id, report_id),
            )

    def rows(self, role: str, report_id: str) -> list[Row]:
        with user_cursor(role) as cur:
            return fetch_all(
                cur,
                "SELECT ROW_ID, KIND, FIELDS, COLLECTED_AT, TIME_KNOWN, SOURCE_PAGE, SOURCE_QUOTE, CONFIDENCE, FLAGS, "
                "STATUS, RECORD_ID, VERSION FROM CLINICAL.REPORT_ROW WHERE REPORT_ID = %s ORDER BY SOURCE_PAGE, ROW_ID",
                (report_id,),
            )

    def row(self, role: str, patient_id: str, row_id: str) -> Row | None:
        with user_cursor(role) as cur:
            return fetch_one(
                cur,
                "SELECT ROW_ID, REPORT_ID, KIND, FIELDS, COLLECTED_AT, TIME_KNOWN, FLAGS, STATUS, VERSION "
                "FROM CLINICAL.REPORT_ROW WHERE PATIENT_ID = %s AND ROW_ID = %s",
                (patient_id, row_id),
            )

    def pages(self, role: str, report_id: str) -> list[Row]:
        with user_cursor(role) as cur:
            return fetch_all(
                cur,
                "SELECT PAGE_NO, PAGE_TEXT FROM CLINICAL.REPORT_PAGE WHERE REPORT_ID = %s ORDER BY PAGE_NO",
                (report_id,),
            )

    def existing_labs(self, role: str, patient_id: str) -> list[Row]:
        with user_cursor(role) as cur:
            return fetch_all(
                cur,
                "SELECT LOINC_CODE, OBSERVED_AT::DATE AS D, VALUE_NUM FROM CLINICAL.LAB_RESULT "
                "WHERE PATIENT_ID = %s AND NOT IS_ARCHIVED",
                (patient_id,),
            )

    def active_medicines(self, role: str, patient_id: str) -> list[str]:
        with user_cursor(role) as cur:
            rows = fetch_all(
                cur,
                "SELECT LOWER(COALESCE(DRUG_NAME, DESCRIPTION)) AS N FROM CLINICAL.MEDICATION "
                "WHERE PATIENT_ID = %s AND IS_ACTIVE AND NOT IS_ARCHIVED",
                (patient_id,),
            )
        return [r["n"] for r in rows if r["n"]]

    def known_drug_names(self, role: str) -> set[str]:
        with user_cursor(role) as cur:
            rows = fetch_all(
                cur,
                "SELECT DISTINCT n.NAME_TEXT FROM KNOWLEDGE.DRUG_NAME_MAP n "
                "JOIN KNOWLEDGE.DRUG d ON d.DRUG_ID = n.DRUG_ID AND d.IN_CORPUS",
            )
        return {r["name_text"] for r in rows}

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
