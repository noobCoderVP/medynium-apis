"""Response fragments used by more than one feature (shared code lives in core, never feature to feature)."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel


class Money(BaseModel):
    amount: float
    currency: Literal["INR"] = "INR"


class Flag(BaseModel):
    type: Literal["NEW_LAB", "NEW_MEDICATION", "RECENT_EMERGENCY", "NEW_DOCUMENT"]
    label: str


class EncounterRef(BaseModel):
    date: dt.date | None = None
    kind: Literal["OUTPATIENT", "EMERGENCY", "HOSPITALIZATION"] | None = None
    label: str | None = None


KIND_LABELS = {
    "EMERGENCY": "Emergency visit",
    "HOSPITALIZATION": "Hospital stay",
    "OUTPATIENT": "Outpatient visit",
}


def flags_from(
    new_labs: int,
    new_medication: bool,
    recent_emergency: bool,
    new_document: bool,
    emergency_date: dt.date | None,
) -> list[Flag]:
    """The change indicators shown on the worklist and in the overview."""
    flags: list[Flag] = []
    if new_labs:
        flags.append(
            Flag(type="NEW_LAB", label=f"{new_labs} new lab{'s' if new_labs != 1 else ''}")
        )
    if new_medication:
        flags.append(Flag(type="NEW_MEDICATION", label="Medication updated"))
    if recent_emergency:
        when = f"{emergency_date.day} {emergency_date:%b}" if emergency_date else "this week"
        flags.append(Flag(type="RECENT_EMERGENCY", label=f"ED visit {when}"))
    if new_document:
        flags.append(Flag(type="NEW_DOCUMENT", label="New document"))
    return flags
