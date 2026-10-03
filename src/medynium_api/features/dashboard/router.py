from typing import Annotated

from fastapi import APIRouter, Depends

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.session import CurrentSession
from medynium_api.features.dashboard.schemas import BriefingResponse, DashboardResponse
from medynium_api.features.dashboard.service import DashboardService

router = APIRouter(tags=["dashboard"])


def get_service(settings: Annotated[Settings, Depends(get_settings)]) -> DashboardService:
    return DashboardService(settings)


Service = Annotated[DashboardService, Depends(get_service)]


@router.get("/dashboard")
def dashboard(session: CurrentSession, service: Service) -> DashboardResponse:
    """Worklist with change flags, recent lab and medication changes, utilisation. No AI call."""
    return service.load(session)


@router.get("/dashboard/briefing")
def briefing(session: CurrentSession, service: Service) -> BriefingResponse:
    """Briefing of recent changes, on request only (A-13). Rules over the caller's own data, no model call."""
    return service.briefing(session)
