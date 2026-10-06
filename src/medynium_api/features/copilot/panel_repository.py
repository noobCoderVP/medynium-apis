"""The assistant's panel tools read the clinician's own panel: the caller's role, so the entitled-patient policy decides
which patients can appear. Every statement is parametrised and recorded verbatim as SQL evidence. The filter values
are bound; the only words that reach the SQL are fixed ones (operators and column names from small whitelists)."""

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from medynium_api.core.evidence.models import SqlEvidence
from medynium_api.core.pagination import like
from medynium_api.core.panel_sql import PENDING_KINDS, pending_query
from medynium_api.core.snowflake.queries import Row, explain_sql, fetch_all
from medynium_api.core.snowflake.role_session import user_cursor

LIMIT = 25
OPS = {"<": "<", "<=": "<=", ">": ">", ">=": ">="}
FLAGS = {
    "NEW_LAB": "w.HAS_NEW_LAB", "NEW_MEDICATION": "w.HAS_NEW_MEDICATION_CHANGE",
    "RECENT_EMERGENCY": "w.HAS_RECENT_EMERGENCY", "NEW_DOCUMENT": "w.HAS_NEW_DOCUMENT",
}  # fmt: skip
ORDER = "w.HAS_RECENT_EMERGENCY DESC, w.FLAG_COUNT DESC, w.LAST_CHANGE_DATE DESC NULLS LAST, w.PATIENT_ID"


class PanelFilters(BaseModel):
    """What a clinician can filter their own patients by. The router model fills this in; extra keys are refused, and
    nothing here is ever SQL: values are bound and operators and columns come from fixed lists."""

    model_config = ConfigDict(extra="forbid")

    diagnosis: str | None = Field(default=None, max_length=60)
    drug: str | None = Field(default=None, max_length=60)
    lab_code: str | None = Field(default=None, max_length=24, pattern=r"^[A-Za-z0-9 .\-]+$")
    lab_op: Literal["<", "<=", ">", ">="] | None = None
    lab_value: float | None = Field(default=None, ge=-1_000_000, le=1_000_000)
    sex: Literal["M", "F"] | None = None
    min_age: int | None = Field(default=None, ge=0, le=120)
    max_age: int | None = Field(default=None, ge=0, le=120)
    flag: Literal["NEW_LAB", "NEW_MEDICATION", "RECENT_EMERGENCY", "NEW_DOCUMENT"] | None = None
    changed: bool = False

    @model_validator(mode="after")
    def _lab_is_whole(self) -> "PanelFilters":
        parts = [self.lab_code, self.lab_op, self.lab_value]
        if any(p is not None for p in parts) and any(p is None for p in parts):
            raise ValueError("a lab filter needs a test, a comparison and a value together")
        return self

    def describe(self) -> str:
        bits = []
        if self.diagnosis:
            bits.append(f"a diagnosis containing '{self.diagnosis}'")
        if self.drug:
            bits.append(f"on {self.drug}")
        if self.lab_code and self.lab_op and self.lab_value is not None:
            bits.append(f"{self.lab_code} {self.lab_op} {self.lab_value:g}")
        if self.sex:
            bits.append("female" if self.sex == "F" else "male")
        if self.min_age is not None:
            bits.append(f"aged {self.min_age} or over")
        if self.max_age is not None:
            bits.append(f"aged {self.max_age} or under")
        if self.flag:
            bits.append("flagged: " + self.flag.lower().replace("_", " "))
        if self.changed:
            bits.append("with recent changes")
        return ", ".join(bits) or "all of them"


def _record(role: str, sql: str, params: list[Any], rows: int, recorded: list[SqlEvidence]) -> None:
    recorded.append(
        SqlEvidence(
            sql_id=f"Q{len(recorded) + 1}", role=role, text=explain_sql(sql, params), row_count=rows,
            ran_at=dt.datetime.now(dt.UTC).replace(tzinfo=None),
        )
    )  # fmt: skip


class PanelQueries:
    def patients(self, role: str, f: PanelFilters, recorded: list[SqlEvidence]) -> list[Row]:
        """The caller's patients, urgent first, narrowed by `f`. With no filters this is the plain worklist."""
        joins: list[str] = []
        join_params: list[Any] = []
        where: list[str] = ["TRUE"]
        params: list[Any] = []
        lab_cols = "NULL AS LAB_VALUE, NULL AS LAB_UNIT, NULL AS LAB_ID, NULL AS LAB_TEST"
        med_cols = "NULL AS MED_ID, NULL AS MED_DRUG"
        if f.lab_code and f.lab_op and f.lab_value is not None:
            lab_cols = "l.LATEST_VALUE AS LAB_VALUE, l.UNIT AS LAB_UNIT, l.LATEST_LAB_ID AS LAB_ID, l.SHORT_NAME AS LAB_TEST"
            joins.append(
                "JOIN ANALYTICS.PATIENT_LAB_LATEST l ON l.PATIENT_ID = w.PATIENT_ID "
                f"AND (LOWER(l.SHORT_NAME) = LOWER(%s) OR l.LOINC_CODE = %s) AND l.LATEST_VALUE {OPS[f.lab_op]} %s"
            )
            join_params += [f.lab_code.strip(), f.lab_code.strip(), f.lab_value]
        if f.drug:
            med_cols = "dm.MED_ID AS MED_ID, dm.DRUG AS MED_DRUG"
            joins.append(
                "JOIN (SELECT PATIENT_ID, MIN(MEDICATION_ID) AS MED_ID, MIN(COALESCE(DRUG_NAME, DESCRIPTION)) AS DRUG "
                "FROM ANALYTICS.CURRENT_MEDICATIONS WHERE DRUG_NAME ILIKE %s OR DESCRIPTION ILIKE %s GROUP BY PATIENT_ID) dm "
                "ON dm.PATIENT_ID = w.PATIENT_ID"
            )
            join_params += [like(f.drug), like(f.drug)]
        if f.diagnosis:
            where.append(
                "EXISTS (SELECT 1 FROM TABLE(FLATTEN(INPUT => p.ACTIVE_DIAGNOSES)) fx "
                "WHERE fx.VALUE:description::VARCHAR ILIKE %s)"
            )
            params.append(like(f.diagnosis))
        if f.sex:
            where.append("UPPER(w.SEX) = %s")
            params.append(f.sex)
        if f.min_age is not None:
            where.append("w.AGE_YEARS >= %s")
            params.append(f.min_age)
        if f.max_age is not None:
            where.append("w.AGE_YEARS <= %s")
            params.append(f.max_age)
        if f.flag:
            where.append(FLAGS[f.flag])
        if f.changed:
            where.append("w.FLAG_COUNT > 0")
        sql = (
            "SELECT w.PATIENT_ID, w.FULL_NAME, w.AGE_YEARS, w.SEX, w.MAIN_DIAGNOSES, w.LAST_ENCOUNTER_DATE, "
            "w.LAST_ENCOUNTER_LABEL, w.NEW_LAB_COUNT, w.HAS_NEW_MEDICATION_CHANGE, w.HAS_RECENT_EMERGENCY, "
            f"w.HAS_NEW_DOCUMENT, {lab_cols}, {med_cols}, COUNT(*) OVER () AS TOTAL "
            "FROM ANALYTICS.DASHBOARD_WORKLIST w JOIN ANALYTICS.PATIENT_360 p ON p.PATIENT_ID = w.PATIENT_ID "
            f"{' '.join(joins)} WHERE {' AND '.join(where)} ORDER BY {ORDER} LIMIT {LIMIT}"
        )
        all_params = [*join_params, *params]
        with user_cursor(role) as cur:
            rows = fetch_all(cur, sql, all_params)
        _record(role, sql, all_params, len(rows), recorded)
        return rows

    def pending(
        self,
        role: str,
        kinds: list[str] | None,
        patient_id: str | None,
        recorded: list[SqlEvidence],
    ) -> list[Row]:
        sql, params = pending_query(kinds, patient_id)
        all_params = [*params, LIMIT, 0]
        with user_cursor(role) as cur:
            rows = fetch_all(cur, sql, all_params)
        _record(role, sql, all_params, len(rows), recorded)
        return rows

    def patient_counts(self, role: str, recorded: list[SqlEvidence]) -> Row | None:
        """How many of the caller's patients need attention and why, over the whole worklist (not just the top rows)."""
        sql = (
            "SELECT COUNT(*) AS TOTAL, COUNT_IF(FLAG_COUNT > 0) AS NEEDS_ATTENTION, COUNT_IF(HAS_RECENT_EMERGENCY) AS EMERGENCY, "
            "COUNT_IF(HAS_NEW_MEDICATION_CHANGE) AS MED_CHANGES, COUNT_IF(HAS_NEW_DOCUMENT) AS NEW_DOCS "
            "FROM ANALYTICS.DASHBOARD_WORKLIST"
        )
        with user_cursor(role) as cur:
            rows = fetch_all(cur, sql, [])
        _record(role, sql, [], len(rows), recorded)
        return rows[0] if rows else None

    def pending_counts(
        self,
        role: str,
        kinds: list[str] | None,
        patient_id: str | None,
        recorded: list[SqlEvidence],
    ) -> list[Row]:
        sql, params = pending_query(kinds, patient_id, count=True)
        with user_cursor(role) as cur:
            rows = fetch_all(cur, sql, params)
        _record(role, sql, params, len(rows), recorded)
        return rows

    def changes(
        self, role: str, since: dt.date, until: dt.date, recorded: list[SqlEvidence]
    ) -> list[Row]:
        sql = (
            "SELECT t.PATIENT_ID, w.FULL_NAME, t.EVENT_DATE, t.EVENT_TYPE, t.TITLE, t.SUMMARY, t.RECORD_ID, "
            "t.RECORD_TABLE, COUNT(*) OVER () AS TOTAL FROM ANALYTICS.PATIENT_TIMELINE t "
            "JOIN ANALYTICS.DASHBOARD_WORKLIST w ON w.PATIENT_ID = t.PATIENT_ID "
            "WHERE t.EVENT_DATE >= %s::DATE AND t.EVENT_DATE <= %s::DATE AND t.EVENT_TYPE <> 'CLAIM' "
            f"ORDER BY t.EVENT_DATE DESC, t.PATIENT_ID, t.EVENT_ID LIMIT {LIMIT}"
        )
        params = [since.isoformat(), until.isoformat()]
        with user_cursor(role) as cur:
            rows = fetch_all(cur, sql, params)
        _record(role, sql, params, len(rows), recorded)
        return rows


__all__ = ["LIMIT", "PENDING_KINDS", "PanelFilters", "PanelQueries"]
