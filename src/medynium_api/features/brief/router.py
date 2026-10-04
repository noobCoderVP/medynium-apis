from typing import Annotated

from fastapi import APIRouter, Depends, Query

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.errors import ErrorBody
from medynium_api.core.intel.models import ChangeSet
from medynium_api.core.session import CurrentSession
from medynium_api.features.brief.schemas import (
    AttentionResponse,
    BriefResponse,
    GapResponse,
    PatientSummary,
    SummaryResponse,
)
from medynium_api.features.brief.service import BriefService

router = APIRouter(tags=["brief"], responses={404: {"model": ErrorBody}, 422: {"model": ErrorBody}})


def get_service(settings: Annotated[Settings, Depends(get_settings)]) -> BriefService:
    return BriefService(settings)


Service = Annotated[BriefService, Depends(get_service)]


@router.get("/patients/{patient_id}/brief")
def brief(patient_id: str, session: CurrentSession, service: Service) -> BriefResponse:
    """What to look at first: attention items, changes since the previous visit, what is missing and the latest results.
    Rules over the caller's own record; no model call. 404 if the patient is missing or denied."""
    return service.brief(session, patient_id)


@router.get("/patients/{patient_id}/brief/summary")
def brief_summary(patient_id: str, session: CurrentSession, service: Service) -> SummaryResponse:
    """A two-to-three sentence written summary of the brief. A model may rephrase the rule signals only; anything it adds
    is discarded and the rule-made headline is used instead."""
    return service.summary(session, patient_id)


@router.get("/patients/{patient_id}/attention")
def attention(patient_id: str, session: CurrentSession, service: Service) -> AttentionResponse:
    """Items that deserve a look, by fixed rules: abnormal or moving results, new medicines or diagnoses, an emergency
    visit, findings and reports waiting. Each names its source record."""
    return service.attention(session, patient_id)


@router.get("/patients/{patient_id}/changes")
def changes(
    patient_id: str,
    session: CurrentSession,
    service: Service,
    from_: Annotated[
        str, Query(alias="from", max_length=16, description="previous_visit, 90d, 1y or YYYY-MM-DD")
    ] = "previous_visit",
) -> ChangeSet:
    """What changed since a starting point, grouped as medication, lab, diagnosis, visit, note and document."""
    return service.changes(session, patient_id, from_)


@router.get("/patients/{patient_id}/gaps")
def gaps(patient_id: str, session: CurrentSession, service: Service) -> GapResponse:
    """What is missing, by fixed rules: usual follow-up results not seen lately, medicines with no indexed label,
    no allergy information. Never a statement that the patient is fine."""
    return service.gaps(session, patient_id)


@router.get("/patients/{patient_id}/summary")
def patient_summary(patient_id: str, session: CurrentSession, service: Service) -> PatientSummary:
    """The stored written summary (markdown) with when it was written, or `exists=false` before the first one."""
    return service.written_summary(session, patient_id)


@router.post("/patients/{patient_id}/summary/refresh")
def refresh_patient_summary(
    patient_id: str, session: CurrentSession, service: Service
) -> PatientSummary:
    """Write the summary again from the record as it is now (about ten seconds) and replace the stored one. Every number
    in it is checked against the record; if the model is unavailable a rule-made summary is stored and labelled so."""
    return service.refresh_written_summary(session, patient_id)
