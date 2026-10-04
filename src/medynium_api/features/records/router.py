from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.errors import ErrorBody
from medynium_api.core.session import CurrentSession, DoctorSession
from medynium_api.features.records.schemas import (
    AllergyIn,
    AllergyUpdate,
    ArchiveBody,
    ArchivedPatientList,
    DiagnosisIn,
    DiagnosisUpdate,
    HistoryList,
    Kind,
    LabIn,
    LabUpdate,
    MedicationIn,
    MedicationUpdate,
    NoteIn,
    NoteUpdate,
    PatientCreate,
    PatientUpdate,
    RecordList,
    RecordRow,
    SyncStatus,
    VisitIn,
    VisitUpdate,
    WriteResult,
)
from medynium_api.features.records.service import RecordService

router = APIRouter(
    tags=["records"],
    responses={404: {"model": ErrorBody}, 409: {"model": ErrorBody}, 403: {"model": ErrorBody}},
)


def get_service(settings: Annotated[Settings, Depends(get_settings)]) -> RecordService:
    return RecordService(settings)


Service = Annotated[RecordService, Depends(get_service)]
Key = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        max_length=64,
        description="Repeating a request with the same key returns the first result instead of writing twice.",
    ),
]


# Patients (doctors only) ------------------------------------------------------------------------------------------
@router.post("/patients", status_code=201)
def register_patient(
    body: PatientCreate, session: DoctorSession, service: Service, key: Key = None
) -> WriteResult:
    """Register a patient. The registering doctor is entitled to them at once. A same-name, same-birth-date patient
    already on the doctor's list is a 409 until `confirm_duplicate` is set."""
    return service.register_patient(session, body, key)


@router.put("/patients/{patient_id}")
def update_patient(
    patient_id: str, body: PatientUpdate, session: DoctorSession, service: Service, key: Key = None
) -> WriteResult:
    """Replace a patient's demographics. `version` must be the one last read."""
    return service.update_patient(session, patient_id, body, body.version, key)


@router.post("/patients/{patient_id}/archive")
def archive_patient(
    patient_id: str, body: ArchiveBody, session: DoctorSession, service: Service
) -> WriteResult:
    """Hide a patient from every screen. Nothing is deleted; restore brings them back."""
    return service.set_patient_archived(session, patient_id, body.version, True, body.reason)


@router.post("/patients/{patient_id}/restore")
def restore_patient(
    patient_id: str, body: ArchiveBody, session: DoctorSession, service: Service
) -> WriteResult:
    return service.set_patient_archived(session, patient_id, body.version, False, body.reason)


@router.get("/archived-patients")
def archived_patients(session: CurrentSession, service: Service) -> ArchivedPatientList:
    """Patients the caller archived (or is entitled to) and can restore."""
    return service.archived_patients(session)


# Records: one create and one replace per kind, so the contract is typed ---------------------------------------------
@router.post("/patients/{patient_id}/diagnoses", status_code=201)
def add_diagnosis(
    patient_id: str, body: DiagnosisIn, session: DoctorSession, service: Service, key: Key = None
) -> WriteResult:
    return service.create(session, patient_id, "diagnoses", body, key)


@router.put("/patients/{patient_id}/diagnoses/{record_id}")
def edit_diagnosis(
    patient_id: str, record_id: str, body: DiagnosisUpdate, session: DoctorSession, service: Service,
    key: Key = None,
) -> WriteResult:  # fmt: skip
    return service.update(session, patient_id, "diagnoses", record_id, body, body.version, key)


@router.post("/patients/{patient_id}/medications", status_code=201)
def add_medication(
    patient_id: str, body: MedicationIn, session: DoctorSession, service: Service, key: Key = None
) -> WriteResult:
    """Add a medicine as written (a generic or an Indian brand). It is matched to the knowledge base, so the
    medication list shows whether its label is indexed."""
    return service.create(session, patient_id, "medications", body, key)


@router.put("/patients/{patient_id}/medications/{record_id}")
def edit_medication(
    patient_id: str, record_id: str, body: MedicationUpdate, session: DoctorSession, service: Service,
    key: Key = None,
) -> WriteResult:  # fmt: skip
    """Edit a medicine. Changing the dose, or setting a stop date, is recorded as a medication change."""
    return service.update(session, patient_id, "medications", record_id, body, body.version, key)


@router.post("/patients/{patient_id}/allergies", status_code=201)
def add_allergy(
    patient_id: str, body: AllergyIn, session: DoctorSession, service: Service, key: Key = None
) -> WriteResult:
    return service.create(session, patient_id, "allergies", body, key)


@router.put("/patients/{patient_id}/allergies/{record_id}")
def edit_allergy(
    patient_id: str, record_id: str, body: AllergyUpdate, session: DoctorSession, service: Service,
    key: Key = None,
) -> WriteResult:  # fmt: skip
    return service.update(session, patient_id, "allergies", record_id, body, body.version, key)


@router.post("/patients/{patient_id}/labs", status_code=201)
def add_lab(
    patient_id: str, body: LabIn, session: DoctorSession, service: Service, key: Key = None
) -> WriteResult:
    """Add a laboratory result. The unit, reference range and flag come from the reference table, not the caller."""
    return service.create(session, patient_id, "labs", body, key)


@router.put("/patients/{patient_id}/labs/{record_id}")
def edit_lab(
    patient_id: str, record_id: str, body: LabUpdate, session: DoctorSession, service: Service,
    key: Key = None,
) -> WriteResult:  # fmt: skip
    return service.update(session, patient_id, "labs", record_id, body, body.version, key)


@router.post("/patients/{patient_id}/notes", status_code=201)
def add_note(
    patient_id: str, body: NoteIn, session: DoctorSession, service: Service, key: Key = None
) -> WriteResult:
    """Add a clinical note. Note text is data: it is shown as plain text and never read as instructions."""
    return service.create(session, patient_id, "notes", body, key)


@router.put("/patients/{patient_id}/notes/{record_id}")
def edit_note(
    patient_id: str, record_id: str, body: NoteUpdate, session: DoctorSession, service: Service,
    key: Key = None,
) -> WriteResult:  # fmt: skip
    return service.update(session, patient_id, "notes", record_id, body, body.version, key)


@router.post("/patients/{patient_id}/visits", status_code=201)
def add_visit(
    patient_id: str, body: VisitIn, session: DoctorSession, service: Service, key: Key = None
) -> WriteResult:
    return service.create(session, patient_id, "visits", body, key)


@router.put("/patients/{patient_id}/visits/{record_id}")
def edit_visit(
    patient_id: str, record_id: str, body: VisitUpdate, session: DoctorSession, service: Service,
    key: Key = None,
) -> WriteResult:  # fmt: skip
    return service.update(session, patient_id, "visits", record_id, body, body.version, key)


# Archive, restore and read, the same for every kind -------------------------------------------------------------------
@router.post("/patients/{patient_id}/{kind}/{record_id}/archive")
def archive_record(
    patient_id: str, kind: Kind, record_id: str, body: ArchiveBody, session: DoctorSession,
    service: Service,
) -> WriteResult:  # fmt: skip
    """Hide one record from every screen and read model. It stays in the history and can be restored."""
    return service.set_archived(
        session, patient_id, kind, record_id, body.version, True, body.reason
    )


@router.post("/patients/{patient_id}/{kind}/{record_id}/restore")
def restore_record(
    patient_id: str, kind: Kind, record_id: str, body: ArchiveBody, session: DoctorSession,
    service: Service,
) -> WriteResult:  # fmt: skip
    return service.set_archived(
        session, patient_id, kind, record_id, body.version, False, body.reason
    )


@router.get("/patients/{patient_id}/records/{kind}")
def list_records(
    patient_id: str,
    kind: Kind,
    session: CurrentSession,
    service: Service,
    include_archived: Annotated[bool, Query()] = False,
) -> RecordList:
    """The editable fields and current version of every record of one kind, for the edit forms."""
    return service.list_records(session, patient_id, kind, include_archived)


@router.get("/patients/{patient_id}/records/{kind}/{record_id}")
def get_record(
    patient_id: str, kind: Kind, record_id: str, session: CurrentSession, service: Service
) -> RecordRow:
    return service.get_record(session, patient_id, kind, record_id)


@router.get("/patients/{patient_id}/history")
def record_history(
    patient_id: str,
    session: CurrentSession,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> HistoryList:
    """Who changed what on this patient, newest first. Written by the database, never by the client."""
    return service.history(session, patient_id, limit)


@router.get("/patients/{patient_id}/sync")
def sync_status(patient_id: str, session: CurrentSession, service: Service) -> SyncStatus:
    """Whether a recent change is still being reflected in the worklist, timeline and latest labs."""
    return service.sync_status(session, patient_id)
