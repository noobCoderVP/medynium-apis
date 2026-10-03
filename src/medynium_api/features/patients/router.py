"""Patient endpoints. A denied patient returns the same 404 as a missing one (SEC-05)."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.errors import ErrorBody
from medynium_api.core.pagination import Paging, SortOrder
from medynium_api.core.session import CurrentSession
from medynium_api.features.patients.filters import PatientFilters
from medynium_api.features.patients.schemas import (
    Claims,
    LabList,
    LabTrend,
    MedicationList,
    NoteDetail,
    NoteList,
    Overview,
    PatientList,
    ShareRequest,
    ShareResult,
    Timeline,
)
from medynium_api.features.patients.service import PatientService

router = APIRouter(tags=["patients"], responses={404: {"model": ErrorBody}})


def get_service(settings: Annotated[Settings, Depends(get_settings)]) -> PatientService:
    return PatientService(settings)


Service = Annotated[PatientService, Depends(get_service)]


@router.get("/patients")
def list_patients(
    session: CurrentSession,
    service: Service,
    page: Paging,
    q: str | None = None,
    changed: bool = False,
    sex: str | None = None,
    kind: Literal["OUTPATIENT", "EMERGENCY", "HOSPITALIZATION"] | None = None,
    flag: Literal["NEW_LAB", "NEW_MEDICATION", "RECENT_EMERGENCY", "NEW_DOCUMENT"] | None = None,
    sort: Literal["name", "age", "last_encounter", "flags"] = "last_encounter",
    order: SortOrder = "desc",
) -> PatientList:
    """The caller's entitled patients, filtered and sorted over all of them before the page is cut.

    `q` searches name, id or diagnosis; `changed` keeps only flagged patients; `flag` narrows to one kind of change.
    """
    filters = PatientFilters(q, changed, sex, kind, flag, sort, order)
    return service.list_patients(session, filters, page)


@router.get("/patients/{patient_id}")
def get_patient(patient_id: str, session: CurrentSession, service: Service) -> Overview:
    """Patient 360 overview. 404 if the patient is missing or the caller is not entitled. Opening a chart is audited."""
    return service.view(session, patient_id)


@router.post("/patients/{patient_id}/share", responses={503: {"model": ErrorBody}})
def share_patient(
    patient_id: str, body: ShareRequest, session: CurrentSession, service: Service
) -> ShareResult:
    """Email a summary of this patient to one recipient. Audited; 404 if missing or not entitled."""
    return service.share(session, patient_id, body)


@router.get("/patients/{patient_id}/medications")
def medications(
    patient_id: str,
    session: CurrentSession,
    service: Service,
    page: Paging,
    status: Literal["active", "all"] = "active",
    q: str | None = None,
    sort: Literal["drug", "started", "last_change"] = "started",
    order: SortOrder = "desc",
) -> MedicationList:
    return service.medications(session, patient_id, status, q, sort, order, page)


@router.get("/patients/{patient_id}/labs")
def labs(
    patient_id: str,
    session: CurrentSession,
    service: Service,
    page: Paging,
    q: str | None = None,
    flag: Literal["abnormal", "LOW", "HIGH", "NORMAL"] | None = None,
    sort: Literal["test", "date", "value"] = "test",
    order: SortOrder = "asc",
) -> LabList:
    """Latest and previous value per test, with reference range and flag."""
    return service.labs(session, patient_id, q, flag, sort, order, page)


@router.get("/patients/{patient_id}/labs/{code}/trend")
def lab_trend(patient_id: str, code: str, session: CurrentSession, service: Service) -> LabTrend:
    """`code` is a LOINC code or a short alias such as eGFR or HbA1c."""
    return service.lab_trend(session, patient_id, code)


@router.get("/patients/{patient_id}/timeline")
def timeline(
    patient_id: str,
    session: CurrentSession,
    service: Service,
    page: Paging,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    types: str | None = None,
    q: str | None = None,
    order: SortOrder = "desc",
) -> Timeline:
    """Merged events. Filter by date range, comma-separated event types and text; `order` is by date."""
    return service.timeline(session, patient_id, from_, to, types, q, order, page)


@router.get("/patients/{patient_id}/claims")
def claims(
    patient_id: str,
    session: CurrentSession,
    service: Service,
    page: Paging,
    status: str | None = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    sort: Literal["date", "billed", "approved", "status"] = "date",
    order: SortOrder = "desc",
) -> Claims:
    """Utilisation (always the full window) and a page of claims, each linked to its encounter."""
    return service.claims(session, patient_id, status, from_, to, sort, order, page)


@router.get("/patients/{patient_id}/notes")
def notes(
    patient_id: str,
    session: CurrentSession,
    service: Service,
    page: Paging,
    q: str | None = None,
    type: str | None = None,
    sort: Literal["date", "title"] = "date",
    order: SortOrder = "desc",
) -> NoteList:
    return service.notes(session, patient_id, q, type, sort, order, page)


@router.get("/patients/{patient_id}/notes/{note_id}")
def note(patient_id: str, note_id: str, session: CurrentSession, service: Service) -> NoteDetail:
    """A note is returned as plain text and is treated as data, never as instructions."""
    return service.note(session, patient_id, note_id)
