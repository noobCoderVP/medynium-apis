import datetime as dt

from pydantic import BaseModel

from medynium_api.core.schemas import EncounterRef, Flag, Money


class WorklistItem(BaseModel):
    patient_id: str
    name: str
    age: int
    sex: str
    last_encounter: EncounterRef
    flags: list[Flag]


class LabChange(BaseModel):
    patient_id: str
    name: str
    test: str
    latest: float
    previous: float | None
    unit: str | None
    date: dt.date
    abnormal: str | None


class MedicationChange(BaseModel):
    patient_id: str
    name: str
    drug: str
    change: str
    date: dt.date


class RecentChanges(BaseModel):
    labs: list[LabChange]
    medications: list[MedicationChange]


class UtilizationSummary(BaseModel):
    window: str = "last_12_months"
    patients: int
    opd_visits: int
    emergency_visits: int
    hospitalizations: int
    procedures: int
    approved: Money


class DashboardResponse(BaseModel):
    as_of: dt.date
    worklist: list[WorklistItem]
    recent_changes: RecentChanges
    utilization: UtilizationSummary


class BriefingItem(BaseModel):
    patient_id: str
    name: str
    text: str
    tag: str = "patient_fact"


class BriefingResponse(BaseModel):
    as_of: dt.date
    generated_by: str = "rules over the dashboard data, no model call"
    items: list[BriefingItem]
    empty_note: str | None = None
