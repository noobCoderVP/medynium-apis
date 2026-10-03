from typing import Annotated

from fastapi import APIRouter, Depends

from medynium_api.core.errors import ErrorBody
from medynium_api.core.session import CurrentSession
from medynium_api.features.findings.schemas import (
    ColleagueList,
    Finding,
    FindingCreate,
    FindingList,
    FindingUpdate,
)
from medynium_api.features.findings.service import FindingService

router = APIRouter(tags=["findings"], responses={404: {"model": ErrorBody}})


def get_service() -> FindingService:
    return FindingService()


Service = Annotated[FindingService, Depends(get_service)]


@router.get("/patients/{patient_id}/findings")
def list_findings(patient_id: str, session: CurrentSession, service: Service) -> FindingList:
    """Decisions recorded on this patient's review statements, open ones first."""
    return service.list_findings(session, patient_id)


@router.get("/patients/{patient_id}/colleagues")
def colleagues(patient_id: str, session: CurrentSession, service: Service) -> ColleagueList:
    """Other active users who have this patient: the people a finding can be escalated to."""
    return service.colleagues(session, patient_id)


@router.post("/patients/{patient_id}/findings", status_code=201)
def raise_finding(
    patient_id: str, body: FindingCreate, session: CurrentSession, service: Service
) -> Finding:
    """Raise a finding from a statement in one of the caller's own answers. Repeating returns the same finding."""
    return service.create(session, patient_id, body)


@router.patch("/findings/{finding_id}")
def decide_finding(
    finding_id: str, body: FindingUpdate, session: CurrentSession, service: Service
) -> Finding:
    """Acknowledge, flag (with a follow-up date), dismiss (with a reason) or escalate (to a colleague)."""
    return service.update(session, finding_id, body)
