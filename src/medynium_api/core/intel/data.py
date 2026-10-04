"""The reads behind patient intelligence. Every statement runs under the caller's own role, so the entitled-patient
policy decides what is visible; the callers check entitlement first so a denied patient is a plain 404."""

import contextvars
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from medynium_api.core.config import get_settings
from medynium_api.core.intel import rules
from medynium_api.core.intel.models import AttentionItem, ChangeSet, GapItem
from medynium_api.core.snowflake.queries import Row, fetch_all, fetch_one, json_value
from medynium_api.core.snowflake.role_session import user_cursor


@dataclass
class Snapshot:
    head: Row
    labs: list[Row]
    meds: list[Row]
    pending: list[Row]
    allergy_count: int
    as_of: dt.date

    @property
    def diagnoses(self) -> list[str]:
        raw = json_value(self.head.get("active_diagnoses")) or []
        return [str(d.get("description", "")) for d in raw if isinstance(d, dict)]


def _one(role: str, sql: str, params: tuple[Any, ...]) -> Row | None:
    with user_cursor(role) as cur:
        return fetch_one(cur, sql, params)


def _all(role: str, sql: str, params: tuple[Any, ...]) -> list[Row]:
    with user_cursor(role) as cur:
        return fetch_all(cur, sql, params)


# The same reads, named for other modules in this package (the written summary gathers more facts than the brief).
rows = _all


def _run(ctx: contextvars.Context, job: tuple[Any, ...]) -> Any:
    return ctx.run(job[0], *job[1:])


def parallel(*jobs: tuple[Any, ...]) -> list[Any]:
    """Independent reads run side by side; each one leases its own connection."""
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [pool.submit(_run, contextvars.copy_context(), job) for job in jobs]
        return [f.result() for f in futures]


def snapshot(role: str, patient_id: str) -> Snapshot | None:
    """None when the patient is not visible to this role (denied and missing look the same)."""
    p = (patient_id,)
    head, labs, meds, pending, allergies = parallel(
        (_one, role, "SELECT FULL_NAME, AGE_YEARS, SEX, ACTIVE_DIAGNOSES, LAST_ENCOUNTER_ID, LAST_ENCOUNTER_DATE, "
         "LAST_ENCOUNTER_KIND, LAST_ENCOUNTER_LABEL, PREVIOUS_ENCOUNTER_DATE, HAS_RECENT_EMERGENCY, HAS_NEW_DOCUMENT "
         "FROM ANALYTICS.PATIENT_360 WHERE PATIENT_ID = %s", p),
        (_all, role, "SELECT LATEST_LAB_ID, SHORT_NAME, LATEST_VALUE, UNIT, LATEST_AT, PREVIOUS_VALUE, PREVIOUS_AT, "
         "ABNORMAL_FLAG, IS_NEW_SINCE_LAST_VISIT FROM ANALYTICS.PATIENT_LAB_LATEST WHERE PATIENT_ID = %s", p),
        (_all, role, "SELECT MEDICATION_ID, DRUG_ID, DRUG_NAME, DESCRIPTION FROM ANALYTICS.CURRENT_MEDICATIONS "
         "WHERE PATIENT_ID = %s ORDER BY START_DATE, MEDICATION_ID", p),
        (_all, role, "SELECT KIND, TITLE, DETAIL, DUE_DATE, RAISED_AT, SOURCE_ID FROM ANALYTICS.PENDING_ITEM "
         "WHERE PATIENT_ID = %s ORDER BY PRIORITY, RAISED_AT DESC LIMIT 20", p),
        (_one, role, "SELECT COUNT(*) AS N FROM CLINICAL.ALLERGY WHERE PATIENT_ID = %s AND NOT IS_ARCHIVED", p),
    )  # fmt: skip
    if head is None:
        return None
    as_of = dt.date.fromisoformat(get_settings().as_of_iso)
    return Snapshot(head, labs, meds, pending, int((allergies or {}).get("n") or 0), as_of)


def since_rows(role: str, patient_id: str, since: dt.date) -> tuple[list[Row], list[Row]]:
    events, reports = parallel(
        (_all, role, "SELECT EVENT_DATE, EVENT_TYPE, TITLE, SUMMARY, RECORD_ID FROM ANALYTICS.PATIENT_TIMELINE "
         "WHERE PATIENT_ID = %s AND EVENT_DATE > %s ORDER BY EVENT_DATE DESC, EVENT_ID LIMIT 60", (patient_id, since)),
        (_all, role, "SELECT REPORT_ID, FILENAME, ROWS_KEPT, EXTRACTED_AT FROM CLINICAL.REPORT WHERE PATIENT_ID = %s "
         "AND STATUS IN ('EXTRACTED', 'REVIEWED') AND EXTRACTED_AT::DATE > %s ORDER BY EXTRACTED_AT DESC LIMIT 10",
         (patient_id, since)),
    )  # fmt: skip
    return events, reports


def attention_items(
    role: str, patient_id: str, snap: Snapshot | None = None
) -> list[AttentionItem] | None:
    snap = snap or snapshot(role, patient_id)
    if snap is None:
        return None
    since = snap.head.get("previous_encounter_date") or snap.as_of - dt.timedelta(days=90)
    events, _ = since_rows(role, patient_id, since)
    return rules.attention(snap.head, snap.labs, events, snap.pending, snap.as_of)


def change_set(
    role: str, patient_id: str, choice: str, snap: Snapshot | None = None
) -> ChangeSet | None:
    """None when the patient is not visible; ValueError when the starting point is not understood."""
    snap = snap or snapshot(role, patient_id)
    if snap is None:
        return None
    resolved = rules.resolve_since(choice, snap.head.get("previous_encounter_date"), snap.as_of)
    if resolved is None:
        raise ValueError("from must be previous_visit, 90d, 1y or a date (YYYY-MM-DD)")
    since, label = resolved
    events, reports = since_rows(role, patient_id, since)
    return rules.changes(since, label, snap.labs, events, reports)


def gap_items(role: str, patient_id: str, snap: Snapshot | None = None) -> list[GapItem] | None:
    snap = snap or snapshot(role, patient_id)
    if snap is None:
        return None
    return rules.gaps(snap.meds, snap.labs, snap.diagnoses, snap.allergy_count, snap.as_of)
