"""Which doctor a record belongs to, for every screen that shows one (timeline, medicines, results, notes, claims).

The record itself does not always say. In order of how specific it is:
  entered_by  the doctor who entered it in this app (the write history names the actor)
  author      the doctor who wrote a note
  provider    the clinician of the visit the record belongs to (medicines, results and diagnoses link to a visit; a visit
              and a claim name their provider)
When none of these exists the record carries the patient's treating doctors, marked as "treating" so it is never passed off as
the author of that record. Reads run under the caller's role."""

import contextvars
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal

from medynium_api.core.snowflake.queries import Row, fetch_all
from medynium_api.core.snowflake.role_session import service_cursor, user_cursor

Basis = Literal["entered_by", "author", "provider", "treating"]
TTL_SECONDS = 20.0


@dataclass(frozen=True)
class Doctor:
    name: str
    speciality: str | None
    basis: Basis


@dataclass
class Directory:
    by_record: dict[str, Doctor] = field(default_factory=dict)
    treating: list[str] = field(default_factory=list)

    def specific(self, *ids: str | None) -> Doctor | None:
        """The doctor the data names for the first id that has one: a record id, then the visit it belongs to."""
        for i in ids:
            if i and i in self.by_record:
                return self.by_record[i]
        return None

    def of(self, *ids: str | None) -> Doctor | None:
        """The named doctor, or else the patient's treating doctor(s), marked as such so it is never passed off as the
        author of that particular record."""
        found = self.specific(*ids)
        if found or not self.treating:
            return found
        return Doctor(", ".join(self.treating), None, "treating")


def title(name: str) -> str:
    name = " ".join(name.split())
    return name if name.lower().startswith(("dr.", "dr ")) else f"Dr. {name}"


def _rows(role: str, sql: str, patient_id: str) -> list[Row]:
    with user_cursor(role) as cur:
        return fetch_all(cur, sql, (patient_id,) * sql.count("%s"))


def _run(ctx: contextvars.Context, fn: Any, *args: Any) -> Any:
    return ctx.run(fn, *args)


def _names(user_ids: Iterable[str]) -> dict[str, str]:
    ids = sorted(set(user_ids))
    if not ids:
        return {}
    marks = ", ".join(["%s"] * len(ids))
    with service_cursor() as cur:
        rows = fetch_all(
            cur,
            f"SELECT USER_ID, DISPLAY_NAME FROM SECURITY.APP_USER WHERE USER_ID IN ({marks})",  # noqa: S608 - placeholders only
            tuple(ids),
        )
    return {r["user_id"]: r["display_name"] for r in rows}


def _treating(patient_id: str) -> list[str]:
    with service_cursor() as cur:
        rows = fetch_all(
            cur,
            "SELECT u.DISPLAY_NAME FROM SECURITY.PATIENT_ENTITLEMENT e JOIN SECURITY.APP_USER u ON u.USER_ID = e.USER_ID "
            "WHERE e.PATIENT_ID = %s AND e.REVOKED_AT IS NULL AND u.STATUS = 'ACTIVE' AND u.ROLE_CODE = 'DOCTOR' "
            "ORDER BY u.DISPLAY_NAME",
            (patient_id,),
        )
    return [title(r["display_name"]) for r in rows]


VISIT_DOCTOR = (
    "SELECT {id} AS RID, p.NAME, p.SPECIALITY FROM CLINICAL.{table} x "
    "JOIN CLINICAL.ENCOUNTER e ON e.ENCOUNTER_ID = x.ENCOUNTER_ID JOIN CLINICAL.PROVIDER p ON p.PROVIDER_ID = e.PROVIDER_ID "
    "WHERE x.PATIENT_ID = %s"
)
QUERIES = {
    "visits": "SELECT e.ENCOUNTER_ID AS RID, p.NAME, p.SPECIALITY FROM CLINICAL.ENCOUNTER e JOIN CLINICAL.PROVIDER p ON p.PROVIDER_ID = e.PROVIDER_ID WHERE e.PATIENT_ID = %s",
    "claims": "SELECT c.CLAIM_ID AS RID, p.NAME, p.SPECIALITY FROM CLINICAL.CLAIM c JOIN CLINICAL.PROVIDER p ON p.PROVIDER_ID = c.PROVIDER_ID WHERE c.PATIENT_ID = %s",
    "linked": " UNION ALL ".join(
        VISIT_DOCTOR.format(id=i, table=t)
        for i, t in (
            ("x.MEDICATION_ID", "MEDICATION"),
            ("x.LAB_ID", "LAB_RESULT"),
            ("x.DIAGNOSIS_ID", "DIAGNOSIS"),
        )
    ),
    "notes": "SELECT NOTE_ID AS RID, AUTHOR AS NAME, NULL AS SPECIALITY FROM CLINICAL.CLINICAL_NOTE WHERE PATIENT_ID = %s AND AUTHOR IS NOT NULL",
    "entered": "SELECT RECORD_ID AS RID, ACTOR_ID FROM CLINICAL.RECORD_HISTORY WHERE PATIENT_ID = %s AND OP = 'CREATE' AND ACTOR_ID IS NOT NULL",
}


def build(role: str, patient_id: str) -> Directory:
    with ThreadPoolExecutor(max_workers=len(QUERIES) + 1) as pool:
        futures = {
            k: pool.submit(_run, contextvars.copy_context(), _rows, role, sql, patient_id)
            for k, sql in QUERIES.items()
        }
        treating = pool.submit(_run, contextvars.copy_context(), _treating, patient_id)
        got = {k: f.result() for k, f in futures.items()}
        treating_names = treating.result()
    directory = Directory(treating=treating_names)
    for r in got["visits"] + got["linked"] + got["claims"]:
        directory.by_record[r["rid"]] = Doctor(title(r["name"]), r["speciality"], "provider")
    for r in got["notes"]:
        directory.by_record[r["rid"]] = Doctor(title(r["name"]), None, "author")
    names = _names(r["actor_id"] for r in got["entered"])
    for r in got["entered"]:
        if r["actor_id"] in names:  # the person who typed it in outranks the visit's clinician
            directory.by_record[r["rid"]] = Doctor(title(names[r["actor_id"]]), None, "entered_by")
    return directory


_cache: dict[tuple[str, str], tuple[float, Directory]] = {}
_lock = threading.Lock()


def directory(role: str, patient_id: str) -> Directory:
    """The doctors behind one patient's records. Kept for a few seconds per caller (two screens often load together)."""
    key = (role, patient_id)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    built = build(role, patient_id)
    with _lock:
        _cache[key] = (now + TTL_SECONDS, built)
    return built


def forget(patient_id: str) -> None:
    """A write or a refresh changed this patient: the next read rebuilds."""
    with _lock:
        for key in [k for k in _cache if k[1] == patient_id]:
            del _cache[key]
