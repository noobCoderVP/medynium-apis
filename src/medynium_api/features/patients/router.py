"""Patient endpoints. A denied patient returns the same 404 as a missing one (SEC-05)."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.errors import ErrorBody
from medynium_api.core.pagination import Paging
from medynium_api.core.session import CurrentSession
from medynium_api.features.patients.schemas import (
    Claims,
    LabLatest,
    LabTrend,
    Medication,
    NoteDetail,
    NoteSummary,
    Overview,
    PatientList,
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
) -> PatientList:
    """The caller's entitled patients. `q` searches name or id; `changed` keeps only flagged patients."""
    return service.list_patients(session, q, changed, page)


@router.get("/patients/{patient_id}")
def get_patient(patient_id: str, session: CurrentSession, service: Service) -> Overview:
    """Patient 360 overview. 404 if the patient is missing or the caller is not entitled."""
    return service.overview(session, patient_id)


@router.get("/patients/{patient_id}/medications")
def medications(
    patient_id: str,
    session: CurrentSession,
    service: Service,
    status: Literal["active", "all"] = "active",
) -> list[Medication]:
    return service.medications(session, patient_id, status)


@router.get("/patients/{patient_id}/labs")
def labs(
    patient_id: str, session: CurrentSession, service: Service, q: str | None = None
) -> list[LabLatest]:
    """Latest and previous value per test, with reference range and flag."""
    return service.labs(session, patient_id, q)


@router.get("/patients/{patient_id}/labs/{code}/trend")
def lab_trend(patient_id: str, code: str, session: CurrentSession, service: Service) -> LabTrend:
    """`code` is a LOINC code or a short alias such as eGFR or HbA1c."""
    return service.lab_trend(session, patient_id, code)


@router.get("/patients/{patient_id}/timeline")
def timeline(
    patient_id: str,
    session: CurrentSession,
    service: Service,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    types: str | None = None,
) -> Timeline:
    """Merged events, newest first. Filter by date range and comma-separated event types."""
    return service.timeline(session, patient_id, from_, to, types)


@router.get("/patients/{patient_id}/claims")
def claims(patient_id: str, session: CurrentSession, service: Service) -> Claims:
    """Utilisation and claims, each linked to its encounter."""
    return service.claims(session, patient_id)


@router.get("/patients/{patient_id}/notes")
def notes(patient_id: str, session: CurrentSession, service: Service) -> list[NoteSummary]:
    return service.notes(session, patient_id)


@router.get("/patients/{patient_id}/notes/{note_id}")
def note(patient_id: str, note_id: str, session: CurrentSession, service: Service) -> NoteDetail:
    """A note is returned as plain text and is treated as data, never as instructions."""
    return service.note(session, patient_id, note_id)
