"""The deterministic pass (A-4): read one patient's facts with SQL under the caller's own role. The statements that
run are recorded verbatim (values filled in) because they are the SQL evidence in the Why? panel (FR-08)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from medynium_api.core.evidence.models import SqlEvidence
from medynium_api.core.snowflake.queries import Row, explain_sql, fetch_all, fetch_one, json_value
from medynium_api.core.snowflake.role_session import user_cursor


@dataclass
class Facts:
    patient_id: str
    name: str
    diagnoses: list[dict[str, Any]]
    meds: list[Row]
    labs: list[Row]
    notes: list[Row]
    sql: list[SqlEvidence] = field(default_factory=list)


class CopilotRepository:
    def patient_facts(self, role: str, patient_id: str) -> Facts | None:
        """None when the patient is not visible to this role (denied and missing look the same)."""
        recorded: list[SqlEvidence] = []

        def run(cur: Any, fetcher: Any, sql: str, params: tuple[Any, ...]) -> Any:
            result = fetcher(cur, sql, params)
            rows = result if isinstance(result, list) else ([] if result is None else [result])
            recorded.append(
                SqlEvidence(
                    sql_id=f"Q{len(recorded) + 1}", role=role, text=explain_sql(sql, params),
                    row_count=len(rows), ran_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )  # fmt: skip
            return result

        with user_cursor(role) as cur:
            head = run(
                cur, fetch_one,
                "SELECT PATIENT_ID, FULL_NAME, ACTIVE_DIAGNOSES FROM ANALYTICS.PATIENT_360 WHERE PATIENT_ID = %s",
                (patient_id,),
            )  # fmt: skip
            if not head:
                return None
            meds = run(
                cur, fetch_all,
                "SELECT MEDICATION_ID, DRUG_ID, DRUG_NAME, DOSE_TEXT, START_DATE, LAST_CHANGE_DATE, CHANGE_NOTE "
                "FROM ANALYTICS.CURRENT_MEDICATIONS WHERE PATIENT_ID = %s ORDER BY START_DATE, MEDICATION_ID",
                (patient_id,),
            )  # fmt: skip
            labs = run(
                cur, fetch_all,
                "SELECT LATEST_LAB_ID, SHORT_NAME, LATEST_VALUE, UNIT, LATEST_AT::DATE AS D, PREVIOUS_VALUE, "
                "PREVIOUS_AT::DATE AS PD, ABNORMAL_FLAG, REF_LOW, REF_HIGH FROM ANALYTICS.PATIENT_LAB_LATEST "
                "WHERE PATIENT_ID = %s ORDER BY IFF(ABNORMAL_FLAG IN ('LOW', 'HIGH'), 0, 1), LATEST_AT DESC LIMIT 8",
                (patient_id,),
            )  # fmt: skip
            notes = run(
                cur, fetch_all,
                "SELECT NOTE_ID, TITLE, NOTE_DATE, LEFT(BODY, 600) AS BODY FROM CLINICAL.CLINICAL_NOTE "
                "WHERE PATIENT_ID = %s ORDER BY NOTE_DATE DESC, NOTE_ID LIMIT 2",
                (patient_id,),
            )  # fmt: skip
        return Facts(
            patient_id=patient_id, name=head["full_name"], diagnoses=list(json_value(head["active_diagnoses"]) or [])[:6],
            meds=meds, labs=labs, notes=notes, sql=recorded,
        )  # fmt: skip


class CopilotQueries:
    """Smaller reads used by the lookup, analyst and knowledge handlers. Same rules: caller's role, recorded SQL."""

    @staticmethod
    def _record(
        role: str, sql: str, params: tuple[Any, ...], rows: int, recorded: list[SqlEvidence]
    ) -> None:
        recorded.append(
            SqlEvidence(
                sql_id=f"Q{len(recorded) + 1}", role=role, text=explain_sql(sql, params), row_count=rows,
                ran_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )  # fmt: skip

    def utilization(self, role: str, patient_id: str, recorded: list[SqlEvidence]) -> Row | None:
        sql = (
            "SELECT OPD_VISITS, EMERGENCY_VISITS, HOSPITALIZATIONS, PROCEDURES, BILLED_INR, APPROVED_INR "
            "FROM ANALYTICS.UTILIZATION WHERE PATIENT_ID = %s"
        )
        with user_cursor(role) as cur:
            row = fetch_one(cur, sql, (patient_id,))
        self._record(role, sql, (patient_id,), 1 if row else 0, recorded)
        return row

    def changed_since_last_visit(
        self, role: str, patient_id: str, recorded: list[SqlEvidence]
    ) -> tuple[Row | None, list[Row]]:
        head_sql = "SELECT PREVIOUS_ENCOUNTER_DATE, LAST_ENCOUNTER_DATE FROM ANALYTICS.PATIENT_360 WHERE PATIENT_ID = %s"
        sql = (
            "SELECT t.EVENT_ID, t.EVENT_DATE, t.EVENT_TYPE, t.TITLE, t.SUMMARY, t.RECORD_ID, t.RECORD_TABLE "
            "FROM ANALYTICS.PATIENT_TIMELINE t JOIN ANALYTICS.PATIENT_360 p ON p.PATIENT_ID = t.PATIENT_ID "
            "WHERE t.PATIENT_ID = %s AND t.EVENT_DATE > p.PREVIOUS_ENCOUNTER_DATE ORDER BY t.EVENT_DATE DESC, t.EVENT_ID LIMIT 20"
        )
        with user_cursor(role) as cur:
            head = fetch_one(cur, head_sql, (patient_id,))
            rows = fetch_all(cur, sql, (patient_id,)) if head else []
        self._record(role, sql, (patient_id,), len(rows), recorded)
        return head, rows

    def run_generated(self, role: str, sql: str, recorded: list[SqlEvidence]) -> list[Row]:
        """Run Analyst's SQL (already guarded) under the caller's role; the row access policy still applies."""
        body = sql.strip().rstrip(";")
        with user_cursor(role) as cur:
            rows = fetch_all(cur, f"SELECT * FROM ({body}) LIMIT 25")
        self._record(role, body, (), len(rows), recorded)
        return rows

    def resolve_names(self, role: str, tokens: list[str]) -> list[Row]:
        if not tokens:
            return []
        marks = ", ".join(["%s"] * len(tokens))
        with user_cursor(role) as cur:
            return fetch_all(
                cur,
                f"SELECT n.NAME_TEXT, n.NAME_KIND, d.DRUG_ID, d.DISPLAY_NAME FROM KNOWLEDGE.DRUG_NAME_MAP n "
                f"JOIN KNOWLEDGE.DRUG d ON d.DRUG_ID = n.DRUG_ID AND d.IN_CORPUS WHERE n.NAME_TEXT IN ({marks})",
                tokens,
            )
