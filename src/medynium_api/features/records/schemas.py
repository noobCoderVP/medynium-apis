"""The write contract: what a clinician may enter, validated before anything reaches Snowflake.

Every model forbids unknown fields (no mass assignment: ids, versions, provenance and the archive flag are set by the
database, never by the caller). Dates are plain dates; instants are converted to UTC. A naive instant is read as IST,
the clinician's local time. Edits carry the `version` last read: a stale one is a conflict, never a silent overwrite.
"""

import datetime as dt
import math
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None
Kind = Literal["diagnoses", "medications", "allergies", "labs", "notes", "visits"]
KINDS: dict[str, str] = {
    "diagnoses": "DIAGNOSIS",
    "medications": "MEDICATION",
    "allergies": "ALLERGY",
    "labs": "LAB_RESULT",
    "notes": "CLINICAL_NOTE",
    "visits": "ENCOUNTER",
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _today() -> dt.date:
    return dt.datetime.now(IST).date()


def _not_future(value: dt.date | None, what: str) -> dt.date | None:
    if value is not None and value > _today() + dt.timedelta(days=1):
        raise ValueError(f"{what} cannot be in the future")
    return value


def to_utc_naive(value: dt.datetime) -> dt.datetime:
    aware = value if value.tzinfo else value.replace(tzinfo=IST)
    return aware.astimezone(dt.UTC).replace(tzinfo=None, microsecond=0)


def _instant_not_future(value: dt.datetime, what: str) -> dt.datetime:
    utc = to_utc_naive(value)
    if utc > dt.datetime.now(dt.UTC).replace(tzinfo=None) + dt.timedelta(minutes=5):
        raise ValueError(f"{what} cannot be in the future")
    return utc


class Versioned(Strict):
    version: int = Field(
        ge=1, description="The version last read. A stale one is refused with 409."
    )


class ArchiveBody(Versioned):
    reason: str | None = Field(default=None, max_length=300)


# Patient --------------------------------------------------------------------------------------------------------
class PatientIn(Strict):
    full_name: Text
    birth_date: dt.date
    sex: Literal["M", "F"]
    city: Short = None
    state: Short = None
    pin_code: Annotated[str, StringConstraints(pattern=r"^\d{6}$")] | None = None
    phone: Annotated[str, StringConstraints(pattern=r"^[0-9+\-\s]{7,16}$")] | None = None
    marital_status: Annotated[str, StringConstraints(max_length=20)] | None = None

    @field_validator("birth_date")
    @classmethod
    def _birth(cls, v: dt.date) -> dt.date:
        if v < dt.date(1900, 1, 1):
            raise ValueError("birth date is not plausible")
        _not_future(v, "birth date")
        return v


class PatientCreate(PatientIn):
    confirm_duplicate: bool = Field(
        default=False,
        description="Set after the clinician confirms a same-name, same-birth-date patient is new.",
    )


class PatientUpdate(PatientIn, Versioned):
    pass


# Clinical records -----------------------------------------------------------------------------------------------
class DiagnosisIn(Strict):
    description: Text
    code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    code_system: Annotated[str, StringConstraints(max_length=40)] | None = None
    onset_date: dt.date | None = None
    resolved_date: dt.date | None = None

    @model_validator(mode="after")
    def _dates(self) -> "DiagnosisIn":
        _not_future(self.onset_date, "onset date")
        _not_future(self.resolved_date, "resolved date")
        if self.onset_date and self.resolved_date and self.resolved_date < self.onset_date:
            raise ValueError("resolved date cannot be before the onset date")
        return self


class MedicationIn(Strict):
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)
    ] = Field(
        description="The medicine as written: a generic or an Indian brand. It is matched to the knowledge base."
    )
    strength_text: Short = None
    dose_text: Short = None
    start_date: dt.date | None = None
    stop_date: dt.date | None = None
    reason_description: Short = None
    change_note: Annotated[str, StringConstraints(max_length=300)] | None = None

    @model_validator(mode="after")
    def _dates(self) -> "MedicationIn":
        _not_future(self.start_date, "start date")
        _not_future(self.stop_date, "stop date")
        if self.start_date and self.stop_date and self.stop_date < self.start_date:
            raise ValueError("stop date cannot be before the start date")
        return self


class AllergyIn(Strict):
    substance: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)
    ]
    reaction: Short = None
    severity: Literal["MILD", "MODERATE", "SEVERE"] | None = None
    is_active: bool = True
    recorded_on: dt.date | None = None

    @field_validator("recorded_on")
    @classmethod
    def _recorded(cls, v: dt.date | None) -> dt.date | None:
        return _not_future(v, "recorded date")


class LabIn(Strict):
    loinc_code: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,7}-[0-9]$")]
    value_num: float
    observed_at: dt.datetime
    encounter_id: str | None = Field(default=None, max_length=40)

    @field_validator("value_num")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0 or v > 1_000_000:
            raise ValueError("value is not plausible")
        return v

    @field_validator("observed_at")
    @classmethod
    def _observed(cls, v: dt.datetime) -> dt.datetime:
        return _instant_not_future(v, "collection time")


class NoteIn(Strict):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    note_type: Literal["OUTPATIENT_NOTE", "ED_NOTE", "DISCHARGE_SUMMARY"] = "OUTPATIENT_NOTE"
    note_date: dt.date | None = None
    body: LongText
    encounter_id: str | None = Field(default=None, max_length=40)

    @field_validator("note_date")
    @classmethod
    def _dated(cls, v: dt.date | None) -> dt.date | None:
        return _not_future(v, "note date")


class VisitIn(Strict):
    started_at: dt.datetime
    ended_at: dt.datetime | None = None
    visit_kind: Literal["OUTPATIENT", "EMERGENCY", "HOSPITALIZATION"]
    description: Short = None
    reason_description: Short = None

    @model_validator(mode="after")
    def _times(self) -> "VisitIn":
        self.started_at = _instant_not_future(self.started_at, "start time")
        if self.ended_at is not None:
            self.ended_at = to_utc_naive(self.ended_at)
            if self.ended_at < self.started_at:
                raise ValueError("end time cannot be before the start time")
        return self


class DiagnosisUpdate(DiagnosisIn, Versioned):
    pass


class MedicationUpdate(MedicationIn, Versioned):
    pass


class AllergyUpdate(AllergyIn, Versioned):
    pass


class LabUpdate(LabIn, Versioned):
    pass


class NoteUpdate(NoteIn, Versioned):
    pass


class VisitUpdate(VisitIn, Versioned):
    pass


# Responses -------------------------------------------------------------------------------------------------------
class WriteResult(BaseModel):
    patient_id: str
    record_id: str
    version: int


class SyncStatus(BaseModel):
    pending: bool = Field(
        description="True while the worklist, timeline and latest labs are still catching up with a recent change."
    )


class RecordRow(BaseModel):
    record_id: str
    version: int
    is_archived: bool
    updated_at: dt.datetime | None = None
    fields: dict[str, Any]


class RecordList(BaseModel):
    items: list[RecordRow]


class HistoryEntry(BaseModel):
    at: dt.datetime
    actor_name: str | None
    entity: str
    record_id: str
    op: Literal["CREATE", "UPDATE", "ARCHIVE", "RESTORE"]
    reason: str | None
    changed: list[str] = Field(description="Names of the fields that changed, for an update.")


class HistoryList(BaseModel):
    items: list[HistoryEntry]


class ArchivedPatient(BaseModel):
    patient_id: str
    full_name: str
    version: int
    archived_at: dt.datetime | None


class ArchivedPatientList(BaseModel):
    items: list[ArchivedPatient]
