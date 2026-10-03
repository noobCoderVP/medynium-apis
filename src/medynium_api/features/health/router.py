from typing import Annotated

from fastapi import APIRouter, Depends

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.session import AdminSession
from medynium_api.features.health.schemas import HealthDetails, HealthResponse
from medynium_api.features.health.service import HealthService

router = APIRouter(tags=["health"])


def get_service(settings: Annotated[Settings, Depends(get_settings)]) -> HealthService:
    return HealthService(settings)


Service = Annotated[HealthService, Depends(get_service)]


@router.get("/health")
def health(service: Service) -> HealthResponse:
    """Public liveness. Reports nothing about configuration."""
    return service.liveness()


@router.get("/health/details")
def health_details(admin: AdminSession, service: Service) -> HealthDetails:
    """Admin only: Snowflake, warehouse state, Cortex objects and audit-write status."""
    return service.details()
