import datetime as dt
from typing import Literal

from pydantic import BaseModel

from medynium_api.core.pagination import Page
from medynium_api.core.schemas import EncounterRef, Flag, Money

LabFlag = Literal["LOW", "HIGH", "NORMAL"]
EventType = Literal[
    "ENCOUNTER", "DIAGNOSIS", "MEDICATION_START", "MEDICATION_CHANGE", "LAB_PANEL", "CLAIM", "NOTE"
]


class PatientListItem(BaseModel):
    patient_id: str
    name: str
    age: int
    sex: str
    main_diagnoses: list[str]
    last_encounter: EncounterRef
    flags: list[Flag]


PatientList = Page[PatientListItem]


class Diagnosis(BaseModel):
    diagnosis_id: str
    description: str
    onset_year: int | None
    code: str | None
    source: str = "CLINICAL.DIAGNOSIS"


class Medication(BaseModel):
    medication_id: str
    drug: str
    description: str | None
    dose: str | None
    strength: str | None
    started: dt.date | None
    stopped: dt.date | None
    last_change_date: dt.date | None
    change: str | None
    in_knowledge_base: bool
    also_sold_as: list[str]
    source: str = "CLINICAL.MEDICATION"


class Reference(BaseModel):
    low: float | None
    high: float | None


class PreviousValue(BaseModel):
    value: float
    date: dt.date


class LabLatest(BaseModel):
    lab_id: str
    test: str
    code: str
    value: float
    unit: str | None
    date: dt.date
    previous: PreviousValue | None
    ref: Reference
    flag: LabFlag | None
    source: str = "CLINICAL.LAB_RESULT"


class TrendPoint(BaseModel):
    lab_id: str
    date: dt.date
    value: float


class LabTrend(BaseModel):
    test: str
    code: str
    unit: str | None
    ref: Reference
    points: list[TrendPoint]


class RecordRef(BaseModel):
    table: str
    id: str


class TimelineEvent(BaseModel):
    event_id: str
    date: dt.date
    type: EventType
    title: str
    summary: str | None
    record: RecordRef
    encounter_id: str | None


class Timeline(BaseModel):
    items: list[TimelineEvent]
    total: int


class Utilization(BaseModel):
    window: str = "last_12_months"
    opd_visits: int
    emergency_visits: int
    hospitalizations: int
    procedures: int
    billed: Money
    approved: Money


class Overview(BaseModel):
    patient_id: str
    name: str
    age: int
    sex: str
    city: str | None
    as_of: dt.date
    diagnoses: list[Diagnosis]
    medications: list[Medication]
    latest_labs: list[LabLatest]
    recent_events: list[TimelineEvent]
    utilization: Utilization
    agent_scope_label: str = "Agent scope: this patient"


class Claim(BaseModel):
    claim_id: str
    encounter_id: str | None
    service_date: dt.date | None
    service: str | None
    status: str
    billed: Money
    approved: Money


class Claims(BaseModel):
    utilization: Utilization
    claims: list[Claim]


class NoteSummary(BaseModel):
    note_id: str
    title: str
    type: str | None
    date: dt.date
    encounter_id: str | None


class NoteDetail(NoteSummary):
    author: str | None
    body: str
