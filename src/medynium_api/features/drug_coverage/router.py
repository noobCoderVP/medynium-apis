from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.errors import ErrorBody
from medynium_api.core.session import AdminSession, CurrentSession
from medynium_api.features.drug_coverage.schemas import (
    Coverage,
    DrugRequest,
    DrugRequestIn,
    DrugRequestList,
    RequestDecision,
)
from medynium_api.features.drug_coverage.service import DrugCoverageService

router = APIRouter(
    tags=["drug coverage"], responses={404: {"model": ErrorBody}, 409: {"model": ErrorBody}}
)


def get_service(settings: Annotated[Settings, Depends(get_settings)]) -> DrugCoverageService:
    return DrugCoverageService(settings)


Service = Annotated[DrugCoverageService, Depends(get_service)]


@router.post("/knowledge/requests", status_code=201)
def request_drug(body: DrugRequestIn, session: CurrentSession, service: Service) -> DrugRequest:
    """Ask for a drug that is not indexed. Nothing is indexed by asking: an admin decides and adds the label."""
    return service.request_drug(session, body)


@router.get("/knowledge/requests")
def my_requests(session: CurrentSession, service: Service) -> DrugRequestList:
    return service.my_requests(session)


@router.get("/admin/knowledge/coverage")
def coverage(admin: AdminSession, service: Service) -> Coverage:
    """What the corpus covers and does not, and which unlabelled medicines are in use among the admin's own patients."""
    return service.coverage(admin)


@router.get("/admin/knowledge/requests")
def all_requests(
    admin: AdminSession,
    service: Service,
    status: Annotated[Literal["OPEN", "ADDED", "DECLINED"] | None, Query()] = None,
) -> DrugRequestList:
    return service.all_requests(status)


@router.patch("/admin/knowledge/requests/{request_id}")
def decide_request(
    request_id: str, body: RequestDecision, admin: AdminSession, service: Service
) -> DrugRequest:
    """Mark a request added (after running the setup script) or declined, with a note."""
    return service.decide(admin, request_id, body)
