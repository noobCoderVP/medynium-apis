"""Patient rules (B-5): entitlement first, denied equals missing, ground-truth shaping of precomputed rows."""

import time
from datetime import date
from typing import Any, NoReturn

from medynium_api.core.access import entitled_patients, log_policy_disagreement
from medynium_api.core.config import Settings
from medynium_api.core.errors import invalid, not_found
from medynium_api.core.pagination import PageParams
from medynium_api.core.schemas import KIND_LABELS, EncounterRef, Money, flags_from
from medynium_api.core.session import Session
from medynium_api.core.snowflake.timing import pad
from medynium_api.features.patients.filters import PatientFilters
from medynium_api.features.patients.history_repository import HistoryRepository
from medynium_api.features.patients.mappers import (
    EVENT_TYPES,
)
from medynium_api.features.patients.mappers import (
    event as _event,
)
from medynium_api.features.patients.mappers import (
    lab as _lab,
)
from medynium_api.features.patients.mappers import (
    medication as _medication,
)
from medynium_api.features.patients.mappers import (
    num as _num,
)
from medynium_api.features.patients.mappers import (
    utilization as _utilization,
)
from medynium_api.features.patients.repository import PatientRepository
from medynium_api.features.patients.schemas import (
    Claim,
    Claims,
    Diagnosis,
    LabList,
    LabTrend,
    MedicationList,
    NoteDetail,
    NoteList,
    NoteSummary,
    Overview,
    PatientList,
    PatientListItem,
    Reference,
    ShareRequest,
    ShareResult,
    Timeline,
    TrendPoint,
)
from medynium_api.features.patients.schemas import RecordRef as RecordRef
from medynium_api.features.patients.sharing import SharingService


class PatientService:
    def __init__(
        self,
        settings: Settings,
        repo: PatientRepository | None = None,
        history: HistoryRepository | None = None,
        sharing: SharingService | None = None,
    ) -> None:
        self.as_of = settings.demo_as_of_date
        self.repo = repo or PatientRepository()
        self.history = history or HistoryRepository()
        self.sharing = sharing or SharingService(settings, self.repo)

    # Entitlement first: the cached API check, then the role-scoped query (the policy is the real guarantee). ----
    @staticmethod
    def _gate(session: Session, patient_id: str) -> float:
        started = time.monotonic()
        if patient_id not in entitled_patients(session.user_id):
            pad(started)
            raise not_found()
        return started

    @staticmethod
    def _missing(session: Session, patient_id: str, started: float) -> NoReturn:
        log_policy_disagreement(session, patient_id)
        pad(started)
        raise not_found()

    def list_patients(
        self, session: Session, filters: PatientFilters, page: PageParams
    ) -> PatientList:
        rows, total = self.repo.list_patients(
            session.snowflake_role, filters, page.limit, page.offset
        )
        items = [
            PatientListItem(
                patient_id=r["patient_id"], name=r["full_name"], age=int(r["age_years"]), sex=r["sex"],
                main_diagnoses=list(self._json(r["main_diagnoses"]) or []),
                last_encounter=EncounterRef(
                    date=r["last_encounter_date"], kind=r["last_encounter_kind"],
                    label=KIND_LABELS.get(r["last_encounter_kind"] or "", r["last_encounter_label"]),
                ),
                flags=flags_from(
                    int(r["new_lab_count"] or 0), bool(r["has_new_medication_change"]), bool(r["has_recent_emergency"]),
                    bool(r["has_new_document"]), r["last_encounter_date"] if r["last_encounter_kind"] == "EMERGENCY" else None,
                ),
            )
            for r in rows
        ]  # fmt: skip
        return PatientList(items=items, total=total, limit=page.limit, offset=page.offset)

    @staticmethod
    def _json(value: Any) -> Any:
        from medynium_api.core.snowflake.queries import json_value

        return json_value(value)

    def overview(self, session: Session, patient_id: str) -> Overview:
        started = self._gate(session, patient_id)
        data = self.repo.overview(session.snowflake_role, patient_id, self.as_of)
        if data is None:
            self._missing(session, patient_id, started)
        p = data["patient"]
        dx = self._json(p["active_diagnoses"]) or []
        return Overview(
            patient_id=p["patient_id"], name=p["full_name"], age=int(p["age_years"]), sex=p["sex"], city=p["city"],
            as_of=date.fromisoformat(self.as_of),
            diagnoses=[Diagnosis(diagnosis_id=d["diagnosis_id"], description=d["description"], onset_year=d.get("onset_year"), code=d.get("code")) for d in dx],
            medications=[_medication(m) for m in data["meds"]],
            latest_labs=[_lab(r) for r in data["labs"]],
            recent_events=[_event(r) for r in data["events"]],
            utilization=_utilization(data["utilization"]),
        )  # fmt: skip

    def share(self, session: Session, patient_id: str, body: ShareRequest) -> ShareResult:
        """Email a summary. The overview load is the entitlement check: denied or missing is the same 404."""
        overview = self.overview(session, patient_id)
        return self.sharing.send(session, overview, body)

    def medications(
        self,
        session: Session,
        patient_id: str,
        status: str,
        q: str | None,
        sort: str | None,
        order: str,
        page: PageParams,
    ) -> MedicationList:
        started = self._gate(session, patient_id)
        result = self.repo.medications(
            session.snowflake_role, patient_id, status != "all", q, sort, order,
            page.limit, page.offset,
        )  # fmt: skip
        if result is None:
            self._missing(session, patient_id, started)
        rows, total = result or ([], 0)
        return MedicationList(
            items=[_medication(r) for r in rows], total=total, limit=page.limit, offset=page.offset
        )

    def labs(
        self,
        session: Session,
        patient_id: str,
        q: str | None,
        flag: str | None,
        sort: str | None,
        order: str,
        page: PageParams,
    ) -> LabList:
        started = self._gate(session, patient_id)
        result = self.repo.labs(
            session.snowflake_role, patient_id, q, flag, sort, order, page.limit, page.offset
        )
        if result is None:
            self._missing(session, patient_id, started)
        rows, total = result or ([], 0)
        return LabList(
            items=[_lab(r) for r in rows], total=total, limit=page.limit, offset=page.offset
        )

    def lab_trend(self, session: Session, patient_id: str, code: str) -> LabTrend:
        started = self._gate(session, patient_id)
        data = self.repo.lab_trend(session.snowflake_role, patient_id, code, self.as_of)
        if data is None:
            self._missing(session, patient_id, started)
        if not data["known"]:
            raise invalid(
                "Unknown lab test code.", [{"field": "code", "problem": "not a known test"}]
            )
        ref = data["ref"]
        return LabTrend(
            test=ref["short_name"], code=ref["loinc_code"], unit=ref["unit"],
            ref=Reference(low=_num(ref["ref_low"]), high=_num(ref["ref_high"])),
            points=[TrendPoint(lab_id=r["lab_id"], date=r["d"], value=float(r["value_num"])) for r in data["points"]],
        )  # fmt: skip

    def timeline(
        self,
        session: Session,
        patient_id: str,
        start: date | None,
        end: date | None,
        types: str | None,
        q: str | None,
        order: str,
        page: PageParams,
    ) -> Timeline:
        wanted = [t.strip().upper() for t in types.split(",") if t.strip()] if types else None
        if wanted and not set(wanted) <= EVENT_TYPES:
            raise invalid(
                "Unknown event type.", [{"field": "types", "problem": "unknown event type"}]
            )
        started = self._gate(session, patient_id)
        rows = self.history.timeline(
            session.snowflake_role, patient_id, start, end, wanted, self.as_of, q, order,
            page.limit, page.offset,
        )  # fmt: skip
        if rows is None:
            self._missing(session, patient_id, started)
        rows = rows or []
        return Timeline(
            items=[_event(r) for r in rows], total=int(rows[0]["total"]) if rows else 0,
            limit=page.limit, offset=page.offset,
        )  # fmt: skip

    def claims(
        self,
        session: Session,
        patient_id: str,
        status: str | None,
        start: date | None,
        end: date | None,
        sort: str | None,
        order: str,
        page: PageParams,
    ) -> Claims:
        started = self._gate(session, patient_id)
        data = self.history.claims(
            session.snowflake_role, patient_id, status, start, end, sort, order,
            page.limit, page.offset,
        )  # fmt: skip
        if data is None:
            self._missing(session, patient_id, started)
        utilization, rows = data
        return Claims(
            total=int(rows[0]["total"]) if rows else 0, limit=page.limit, offset=page.offset,
            utilization=_utilization(utilization),
            claims=[
                Claim(
                    claim_id=r["claim_id"], encounter_id=r["encounter_id"], service_date=r["service_date"],
                    service=r["service_text"], status=r["status"], billed=Money(amount=float(r["billed_inr"] or 0)),
                    approved=Money(amount=float(r["approved_inr"] or 0)),
                )
                for r in rows
            ],
        )  # fmt: skip

    def notes(
        self,
        session: Session,
        patient_id: str,
        q: str | None,
        note_type: str | None,
        sort: str | None,
        order: str,
        page: PageParams,
    ) -> NoteList:
        started = self._gate(session, patient_id)
        rows = self.history.notes(
            session.snowflake_role, patient_id, q, note_type, sort, order, page.limit, page.offset
        )
        if rows is None:
            self._missing(session, patient_id, started)
        rows = rows or []
        return NoteList(
            items=[
                NoteSummary(note_id=r["note_id"], title=r["title"], type=r["note_type"], date=r["note_date"], encounter_id=r["encounter_id"])
                for r in rows
            ],
            total=int(rows[0]["total"]) if rows else 0, limit=page.limit, offset=page.offset,
        )  # fmt: skip

    def note(self, session: Session, patient_id: str, note_id: str) -> NoteDetail:
        started = self._gate(session, patient_id)
        r = self.history.note(session.snowflake_role, patient_id, note_id)
        if r is None:
            pad(started)
            raise not_found()
        return NoteDetail(
            note_id=r["note_id"], title=r["title"], type=r["note_type"], date=r["note_date"],
            encounter_id=r["encounter_id"], author=r["author"], body=r["body"],
        )  # fmt: skip
