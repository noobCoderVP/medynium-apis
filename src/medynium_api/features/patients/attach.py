"""Put the doctor's name on the records a screen shows (see core/intel/doctors.py for where each name comes from)."""

from collections.abc import Iterable
from typing import Any

from medynium_api.core.intel import doctors
from medynium_api.core.intel.doctors import Directory, Doctor
from medynium_api.core.schemas import Money
from medynium_api.features.patients.schemas import (
    Claim,
    DoctorRef,
    LabLatest,
    Medication,
    NoteSummary,
    Overview,
    TimelineEvent,
)


def directory(role: str, patient_id: str) -> Directory:
    """Who is behind each record. A failure here never hides the record itself, only the doctor's name."""
    try:
        return doctors.directory(role, patient_id)
    except Exception:
        return Directory()


def ref(d: Doctor | None) -> DoctorRef | None:
    return DoctorRef(name=d.name, speciality=d.speciality, basis=d.basis) if d else None


def claim(r: dict[str, Any], who: Directory) -> Claim:
    return Claim(
        claim_id=r["claim_id"], encounter_id=r["encounter_id"], service_date=r["service_date"],
        service=r["service_text"], status=r["status"], billed=Money(amount=float(r["billed_inr"] or 0)),
        approved=Money(amount=float(r["approved_inr"] or 0)), doctor=ref(who.of(r["claim_id"], r["encounter_id"])),
    )  # fmt: skip


def medicines(items: Iterable[Medication], who: Directory) -> None:
    for m in items:
        m.doctor = ref(who.of(m.medication_id))


def labs(items: Iterable[LabLatest], who: Directory) -> None:
    for lab in items:
        lab.doctor = ref(who.of(lab.lab_id))


def events(items: Iterable[TimelineEvent], who: Directory) -> None:
    for e in items:
        e.doctor = ref(who.of(e.record.id, e.encounter_id))


def notes(items: Iterable[NoteSummary], who: Directory) -> None:
    for n in items:
        n.doctor = ref(who.of(n.note_id, n.encounter_id))


def overview(o: Overview, who: Directory) -> None:
    o.treating_doctors = who.treating
    for d in o.diagnoses:
        d.doctor = ref(who.of(d.diagnosis_id))
    medicines(o.medications, who)
    labs(o.latest_labs, who)
    events(o.recent_events, who)
