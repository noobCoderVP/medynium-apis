from typing import Annotated

from fastapi import APIRouter, Depends, Query

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.errors import ErrorBody
from medynium_api.core.pagination import Paging
from medynium_api.core.session import CurrentSession, DoctorSession
from medynium_api.features.pending.schemas import Kind, LabReviewed, PendingPage, PendingSummary
from medynium_api.features.pending.service import PendingService

router = APIRouter(tags=["pending"], responses={404: {"model": ErrorBody}})


def get_service(settings: Annotated[Settings, Depends(get_settings)]) -> PendingService:
    return PendingService(settings)


Service = Annotated[PendingService, Depends(get_service)]


@router.get("/pending")
def pending(
    session: CurrentSession,
    service: Service,
    paging: Paging,
    kind: Annotated[list[Kind] | None, Query(description="Narrow to these kinds.")] = None,
    patient_id: Annotated[str | None, Query(max_length=20)] = None,
) -> PendingPage:
    """Everything waiting on the caller across the patients they are entitled to, most urgent first. No AI call."""
    return service.page(session, list(kind) if kind else None, patient_id, paging)


@router.get("/pending/summary")
def pending_summary(session: CurrentSession, service: Service) -> PendingSummary:
    """Counts for the navigation badge and the dashboard."""
    return service.summary(session)


@router.post("/patients/{patient_id}/labs/{lab_id}/review")
def review_lab(
    patient_id: str, lab_id: str, session: DoctorSession, service: Service
) -> LabReviewed:
    """Mark an abnormal result as reviewed so it leaves the pending list. A doctor's act; repeating is harmless."""
    return service.review_lab(session, patient_id, lab_id)
