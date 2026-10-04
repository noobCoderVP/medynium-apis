"""Create, edit, archive and restore patients and clinical records (production plan, Phase 1).

Order of every write: rate limit, the cached entitlement check (a denied patient is audited and answered exactly like a
missing one), then the INTAKE procedure, which checks the actor and the entitlement again inside Snowflake, enforces the
row version, writes the history row and rebuilds the patient's read models. Only a doctor writes. The agent never does:
nothing in the copilot imports this feature.
"""

import time
from typing import Any

from pydantic import BaseModel

from medynium_api.core.access import clear_cache, require_patient
from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.config import Settings
from medynium_api.core.errors import ApiError, ErrorCode, conflict, forbidden, invalid, not_found
from medynium_api.core.refresh import pending, refresh_worker
from medynium_api.core.security.ratelimit import write_limiter
from medynium_api.core.session import Session
from medynium_api.core.snowflake.queries import json_value
from medynium_api.core.snowflake.timing import pad
from medynium_api.features.records.repository import READ, RecordRepository
from medynium_api.features.records.schemas import (
    KINDS,
    ArchivedPatient,
    ArchivedPatientList,
    HistoryEntry,
    HistoryList,
    PatientCreate,
    RecordList,
    RecordRow,
    SyncStatus,
    WriteResult,
)

BOOKKEEPING = {
    "VERSION", "UPDATED_AT", "UPDATED_BY", "ENTERED_BY", "ENTRY_SOURCE", "ARCHIVED_AT", "ARCHIVED_BY",
}  # fmt: skip
LOCAL_ONLY = {"version", "confirm_duplicate"}


def payload_of(body: BaseModel) -> dict[str, Any]:
    """The editable fields as JSON for the procedure. Version and flags the caller sends never go through."""
    return body.model_dump(mode="json", exclude=LOCAL_ONLY)


class RecordService:
    def __init__(self, settings: Settings, repo: RecordRepository | None = None) -> None:
        self.settings = settings
        self.repo = repo or RecordRepository()

    # Shared steps ---------------------------------------------------------------------------------------------
    def _audit(
        self,
        session: Session,
        action: str,
        patient_id: str | None,
        outcome: str,
        detail: str | None,
    ) -> None:
        entry = AuditEntry(
            action=action, patient_id=patient_id, cost_note="no model call", outcome=outcome,
            outcome_detail=detail,
        )  # fmt: skip
        write_audit(session, entry, strict=outcome == "OK")

    def _guard(self, session: Session, patient_id: str, action: str) -> None:
        """Entitlement before anything is sent: a denied patient is audited and looks exactly like a missing one."""
        write_limiter.check(session.user_id)
        started = time.monotonic()
        try:
            require_patient(session, patient_id)
        except ApiError:
            self._audit(session, action, patient_id, "DENIED", None)
            pad(started)
            raise

    def _outcome(
        self,
        session: Session,
        result: dict[str, Any],
        action: str,
        patient_id: str | None,
        started: float,
    ) -> WriteResult:
        if result.get("ok"):
            record_id = str(result["record_id"])
            self._audit(session, action, str(result["patient_id"]), "OK", record_id)
            return WriteResult(
                patient_id=str(result["patient_id"]),
                record_id=record_id,
                version=int(result["version"]),
            )
        error = result.get("error")
        if error in ("denied", "not_found"):
            self._audit(
                session, action, patient_id, "DENIED" if error == "denied" else "ERROR", error
            )
            pad(started)
            raise not_found()
        self._audit(session, action, patient_id, "ERROR", str(error))
        if error == "forbidden":
            raise forbidden("Only doctors can change the record.")
        if error == "conflict":
            raise conflict("This record was changed by someone else. Reload it and try again.")
        if error == "invalid":
            raise invalid(str(result.get("detail") or "The request was not valid."))
        raise ApiError(ErrorCode.INTERNAL, "The change could not be saved.")

    # Patients -------------------------------------------------------------------------------------------------
    def register_patient(
        self, session: Session, body: PatientCreate, key: str | None
    ) -> WriteResult:
        write_limiter.check(session.user_id)
        if not body.confirm_duplicate and self.repo.find_duplicate(
            session.snowflake_role, body.full_name, body.birth_date.isoformat()
        ):
            raise conflict(
                "A patient with this name and date of birth is already on your list. "
                "Confirm to add another."
            )
        started = time.monotonic()
        result = self.repo.register_patient(
            session.user_id, payload_of(body), key, self.settings.as_of_iso
        )
        out = self._outcome(session, result, "WRITE_PATIENT_CREATE", None, started)
        clear_cache(
            session.user_id
        )  # the creator is entitled at once; do not wait out the 30 s cache
        refresh_worker.submit(
            out.patient_id
        )  # the case vector for similar-patient search is built in the background
        return out

    def update_patient(
        self, session: Session, patient_id: str, body: BaseModel, version: int, key: str | None
    ) -> WriteResult:
        return self._write(
            session,
            "PATIENT",
            "UPDATE",
            patient_id,
            patient_id,
            version,
            payload_of(body),
            key,
            None,
        )

    def set_patient_archived(
        self, session: Session, patient_id: str, version: int, archived: bool, reason: str | None
    ) -> WriteResult:
        """Archive hides the patient from every screen; restore brings them back. Nothing is deleted."""
        op = "ARCHIVE" if archived else "RESTORE"
        return self._write(
            session, "PATIENT", op, patient_id, patient_id, version, None, None, reason, sync=True
        )

    # Records --------------------------------------------------------------------------------------------------
    def _write(
        self, session: Session, entity: str, op: str, patient_id: str, record_id: str | None,
        version: int | None, payload: dict[str, Any] | None, key: str | None, reason: str | None,
        sync: bool = False,
    ) -> WriteResult:  # fmt: skip
        action = f"WRITE_{entity}_{op}"
        self._guard(session, patient_id, action)
        started = time.monotonic()
        result = self.repo.write(
            session.user_id, entity, op, patient_id, record_id, version, payload, key, reason,
            self.settings.as_of_iso,
        )  # fmt: skip
        out = self._outcome(session, result, action, patient_id, started)
        if sync:  # hiding or restoring a whole patient must show at once, so this one waits for the refresh
            refresh_worker.refresh_now(patient_id)
        else:  # the worklist, timeline and latest labs catch up in the background
            refresh_worker.submit(patient_id)
        return out

    def create(
        self, session: Session, patient_id: str, kind: str, body: BaseModel, key: str | None
    ) -> WriteResult:
        return self._write(
            session, KINDS[kind], "CREATE", patient_id, None, None, payload_of(body), key, None
        )

    def update(
        self, session: Session, patient_id: str, kind: str, record_id: str, body: BaseModel,
        version: int, key: str | None,
    ) -> WriteResult:  # fmt: skip
        return self._write(
            session,
            KINDS[kind],
            "UPDATE",
            patient_id,
            record_id,
            version,
            payload_of(body),
            key,
            None,
        )

    def set_archived(
        self, session: Session, patient_id: str, kind: str, record_id: str, version: int,
        archived: bool, reason: str | None,
    ) -> WriteResult:  # fmt: skip
        op = "ARCHIVE" if archived else "RESTORE"
        return self._write(
            session, KINDS[kind], op, patient_id, record_id, version, None, None, reason
        )

    # Reads ----------------------------------------------------------------------------------------------------
    def sync_status(self, session: Session, patient_id: str) -> SyncStatus:
        """Is a refresh of this patient's read models still owed? Entitlement first, like any read."""
        require_patient(session, patient_id)
        return SyncStatus(pending=pending(patient_id))

    @staticmethod
    def _row(entity: str, row: dict[str, Any]) -> RecordRow:
        fields = {name.lower(): row[name.lower()] for name in READ[entity][2]}
        return RecordRow(
            record_id=row["record_id"], version=int(row["version"]), is_archived=bool(row["is_archived"]),
            updated_at=row["updated_at"], fields=fields,
        )  # fmt: skip

    def list_records(
        self, session: Session, patient_id: str, kind: str, include_archived: bool
    ) -> RecordList:
        require_patient(session, patient_id)
        entity = KINDS[kind]
        rows = self.repo.list_records(session.snowflake_role, patient_id, entity, include_archived)
        return RecordList(items=[self._row(entity, r) for r in rows])

    def get_record(self, session: Session, patient_id: str, kind: str, record_id: str) -> RecordRow:
        require_patient(session, patient_id)
        entity = KINDS[kind]
        row = self.repo.get_record(session.snowflake_role, patient_id, entity, record_id)
        if row is None:
            raise not_found()
        return self._row(entity, row)

    def history(self, session: Session, patient_id: str, limit: int) -> HistoryList:
        require_patient(session, patient_id)
        rows = self.repo.history(session.snowflake_role, patient_id, limit)
        names = self.repo.names({r["actor_id"] for r in rows})
        return HistoryList(
            items=[
                HistoryEntry(
                    at=r["at"], actor_name=names.get(r["actor_id"]), entity=r["entity"],
                    record_id=r["record_id"], op=r["op"], reason=r["reason"],
                    changed=changed_fields(r["before_json"], r["after_json"]),
                )
                for r in rows
            ]
        )  # fmt: skip

    def archived_patients(self, session: Session) -> ArchivedPatientList:
        rows = self.repo.archived_patients(session.snowflake_role)
        return ArchivedPatientList(
            items=[
                ArchivedPatient(
                    patient_id=r["patient_id"], full_name=r["full_name"], version=int(r["version"]),
                    archived_at=r["archived_at"],
                )
                for r in rows
            ]
        )  # fmt: skip


def changed_fields(before: Any, after: Any) -> list[str]:
    """Which fields an edit changed, from the two stored images, bookkeeping columns left out."""
    old, new = json_value(before) or {}, json_value(after) or {}
    if not isinstance(old, dict) or not isinstance(new, dict) or not old:
        return []
    return sorted(
        key.lower()
        for key in new
        if key not in BOOKKEEPING and key not in ("IS_ARCHIVED",) and old.get(key) != new.get(key)
    )
