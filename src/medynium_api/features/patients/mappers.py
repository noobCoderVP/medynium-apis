"""Row-to-schema mapping for the patient reads (precomputed rows in, API shapes out)."""

import json
from typing import Any

from medynium_api.core.schemas import Money
from medynium_api.features.patients.schemas import (
    LabLatest,
    Medication,
    PreviousValue,
    Reference,
    TimelineEvent,
    Utilization,
)

EVENT_TYPES = {
    "ENCOUNTER",
    "DIAGNOSIS",
    "MEDICATION_START",
    "MEDICATION_CHANGE",
    "LAB_PANEL",
    "CLAIM",
    "NOTE",
}


def num(value: Any) -> float | None:
    return float(value) if value is not None else None


def utilization(row: dict[str, Any]) -> Utilization:
    return Utilization(
        opd_visits=int(row.get("opd_visits", 0)), emergency_visits=int(row.get("emergency_visits", 0)),
        hospitalizations=int(row.get("hospitalizations", 0)), procedures=int(row.get("procedures", 0)),
        billed=Money(amount=float(row.get("billed_inr", 0))), approved=Money(amount=float(row.get("approved_inr", 0))),
    )  # fmt: skip


def lab(r: dict[str, Any]) -> LabLatest:
    return LabLatest(
        lab_id=r["latest_lab_id"], test=r["short_name"], code=r["loinc_code"], value=float(r["latest_value"]),
        unit=r["unit"], date=r["d"],
        previous=PreviousValue(value=float(r["previous_value"]), date=r["pd"]) if r["previous_value"] is not None else None,
        ref=Reference(low=num(r["ref_low"]), high=num(r["ref_high"])), flag=r["abnormal_flag"],
    )  # fmt: skip


def event(r: dict[str, Any]) -> TimelineEvent:
    return TimelineEvent(
        event_id=r["event_id"], date=r["event_date"], type=r["event_type"], title=r["title"],
        summary=r["summary"], record={"table": r["record_table"], "id": r["record_id"]},
        encounter_id=r["encounter_id"],
    )  # fmt: skip


def medication(r: dict[str, Any]) -> Medication:
    brands = r.get("brands")
    if isinstance(brands, str):
        brands = json.loads(brands)
    return Medication(
        medication_id=r["medication_id"], drug=r["drug_name"] or r["description"] or "Unknown", description=r["description"],
        dose=r["dose_text"], strength=r["strength_text"], started=r["start_date"], stopped=r["stop_date"],
        last_change_date=r["last_change_date"], change=r["change_note"], in_knowledge_base=bool(r["in_kb"]),
        also_sold_as=[str(b).title() for b in (brands or [])],
    )  # fmt: skip
