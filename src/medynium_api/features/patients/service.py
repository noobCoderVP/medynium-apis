"""Patient rules (B-5): entitlement first, denied equals missing, ground-truth shaping of precomputed rows."""

import time
from datetime import date
from typing import Any

from medynium_api.core.access import entitled_patients, log_policy_disagreement
from medynium_api.core.config import Settings
from medynium_api.core.errors import invalid, not_found
from medynium_api.core.pagination import PageParams
from medynium_api.core.schemas import KIND_LABELS, EncounterRef, Money, flags_from
from medynium_api.core.session import Session
from medynium_api.core.snowflake.timing import pad
from medynium_api.features.patients.history_repository import HistoryRepository
from medynium_api.features.patients.repository import PatientRepository
from medynium_api.features.patients.schemas import (
    Claim,
    Claims,
    Diagnosis,
    LabLatest,
    LabTrend,
    Medication,
    NoteDetail,
    NoteSummary,
    Overview,
    PatientList,
    PatientListItem,
    PreviousValue,
    Reference,
    Timeline,
    TimelineEvent,
    TrendPoint,
    Utilization,
)
from medynium_api.features.patients.schemas import RecordRef as RecordRef

EVENT_TYPES = {
    "ENCOUNTER",
    "DIAGNOSIS",
    "MEDICATION_START",
    "MEDICATION_CHANGE",
    "LAB_PANEL",
    "CLAIM",
    "NOTE",
}


def _num(value: Any) -> float | None:
    return float(value) if value is not None else None


def _utilization(row: dict[str, Any]) -> Utilization:
    return Utilization(
        opd_visits=int(row.get("opd_visits", 0)), emergency_visits=int(row.get("emergency_visits", 0)),
        hospitalizations=int(row.get("hospitalizations", 0)), procedures=int(row.get("procedures", 0)),
        billed=Money(amount=float(row.get("billed_inr", 0))), approved=Money(amount=float(row.get("approved_inr", 0))),
    )  # fmt: skip


def _lab(r: dict[str, Any]) -> LabLatest:
    return LabLatest(
        lab_id=r["latest_lab_id"], test=r["short_name"], code=r["loinc_code"], value=float(r["latest_value"]),
        unit=r["unit"], date=r["d"],
        previous=PreviousValue(value=float(r["previous_value"]), date=r["pd"]) if r["previous_value"] is not None else None,
        ref=Reference(low=_num(r["ref_low"]), high=_num(r["ref_high"])), flag=r["abnormal_flag"],
    )  # fmt: skip


def _event(r: dict[str, Any]) -> TimelineEvent:
    return TimelineEvent(
        event_id=r["event_id"], date=r["event_date"], type=r["event_type"], title=r["title"],
        summary=r["summary"], record={"table": r["record_table"], "id": r["record_id"]},
        encounter_id=r["encounter_id"],
    )  # fmt: skip


def _medication(r: dict[str, Any]) -> Medication:
    brands = r.get("brands")
    if isinstance(brands, str):
        import json

        brands = json.loads(brands)
    return Medication(
        medication_id=r["medication_id"], drug=r["drug_name"] or r["description"] or "Unknown", description=r["description"],
        dose=r["dose_text"], strength=r["strength_text"], started=r["start_date"], stopped=r["stop_date"],
        last_change_date=r["last_change_date"], change=r["change_note"], in_knowledge_base=bool(r["in_kb"]),
        also_sold_as=[str(b).title() for b in (brands or [])],
    )  # fmt: skip


class PatientService:
    def __init__(
        self,
        settings: Settings,
        repo: PatientRepository | None = None,
        history: HistoryRepository | None = None,
    ) -> None:
        self.as_of = settings.demo_as_of_date
        self.repo = repo or PatientRepository()
        self.history = history or HistoryRepository()

    # Entitlement first: the cached API check, then the role-scoped query (the policy is the real guarantee). ----
    @staticmethod
    def _gate(session: Session, patient_id: str) -> float:
        started = time.monotonic()
        if patient_id not in entitled_patients(session.user_id):
            pad(started)
            raise not_found()
        return started

    @staticmethod
    def _missing(session: Session, patient_id: str, started: float) -> None:
        log_policy_disagreement(session, patient_id)
        pad(started)
        raise not_found()

    def list_patients(
        self, session: Session, q: str | None, changed: bool, page: PageParams
    ) -> PatientList:
        rows, total = self.repo.list_patients(
            session.snowflake_role, q, changed, page.limit, page.offset
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
        p = data["patient"]  # type: ignore[index]
        dx = self._json(p["active_diagnoses"]) or []
        return Overview(
            patient_id=p["patient_id"], name=p["full_name"], age=int(p["age_years"]), sex=p["sex"], city=p["city"],
            as_of=date.fromisoformat(self.as_of),
            diagnoses=[Diagnosis(diagnosis_id=d["diagnosis_id"], description=d["description"], onset_year=d.get("onset_year"), code=d.get("code")) for d in dx],
            medications=[_medication(m) for m in data["meds"]],  # type: ignore[index]
            latest_labs=[_lab(r) for r in data["labs"]],  # type: ignore[index]
            recent_events=[_event(r) for r in data["events"]],  # type: ignore[index]
            utilization=_utilization(data["utilization"]),  # type: ignore[index]
        )  # fmt: skip

    def medications(self, session: Session, patient_id: str, status: str) -> list[Medication]:
        started = self._gate(session, patient_id)
        rows = self.repo.medications(
            session.snowflake_role, patient_id, active_only=status != "all"
        )
        if rows is None:
            self._missing(session, patient_id, started)
        return [_medication(r) for r in rows or []]

    def labs(self, session: Session, patient_id: str, q: str | None) -> list[LabLatest]:
        started = self._gate(session, patient_id)
        rows = self.repo.labs(session.snowflake_role, patient_id, q)
        if rows is None:
            self._missing(session, patient_id, started)
        return [_lab(r) for r in rows or []]

    def lab_trend(self, session: Session, patient_id: str, code: str) -> LabTrend:
        started = self._gate(session, patient_id)
        data = self.repo.lab_trend(session.snowflake_role, patient_id, code, self.as_of)
        if data is None:
            self._missing(session, patient_id, started)
        if not data["known"]:  # type: ignore[index]
            raise invalid(
                "Unknown lab test code.", [{"field": "code", "problem": "not a known test"}]
            )
        ref = data["ref"]  # type: ignore[index]
        return LabTrend(
            test=ref["short_name"], code=ref["loinc_code"], unit=ref["unit"],
            ref=Reference(low=_num(ref["ref_low"]), high=_num(ref["ref_high"])),
            points=[TrendPoint(lab_id=r["lab_id"], date=r["d"], value=float(r["value_num"])) for r in data["points"]],  # type: ignore[index]
        )  # fmt: skip

    def timeline(
        self,
        session: Session,
        patient_id: str,
        start: date | None,
        end: date | None,
        types: str | None,
    ) -> Timeline:
        wanted = [t.strip().upper() for t in types.split(",") if t.strip()] if types else None
        if wanted and not set(wanted) <= EVENT_TYPES:
            raise invalid(
                "Unknown event type.", [{"field": "types", "problem": "unknown event type"}]
            )
        started = self._gate(session, patient_id)
        rows = self.history.timeline(
            session.snowflake_role, patient_id, start, end, wanted, self.as_of
        )
        if rows is None:
            self._missing(session, patient_id, started)
        rows = rows or []
        return Timeline(items=[_event(r) for r in rows], total=int(rows[0]["total"]) if rows else 0)

    def claims(self, session: Session, patient_id: str) -> Claims:
        started = self._gate(session, patient_id)
        data = self.history.claims(session.snowflake_role, patient_id)
        if data is None:
            self._missing(session, patient_id, started)
        return Claims(
            utilization=_utilization(data["utilization"]),  # type: ignore[index, arg-type]
            claims=[
                Claim(
                    claim_id=r["claim_id"], encounter_id=r["encounter_id"], service_date=r["service_date"],
                    service=r["service_text"], status=r["status"], billed=Money(amount=float(r["billed_inr"] or 0)),
                    approved=Money(amount=float(r["approved_inr"] or 0)),
                )
                for r in data["claims"]  # type: ignore[index, union-attr]
            ],
        )  # fmt: skip

    def notes(self, session: Session, patient_id: str) -> list[NoteSummary]:
        started = self._gate(session, patient_id)
        rows = self.history.notes(session.snowflake_role, patient_id)
        if rows is None:
            self._missing(session, patient_id, started)
        return [
            NoteSummary(note_id=r["note_id"], title=r["title"], type=r["note_type"], date=r["note_date"], encounter_id=r["encounter_id"])
            for r in rows or []
        ]  # fmt: skip

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
