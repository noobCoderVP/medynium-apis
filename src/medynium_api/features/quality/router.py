from typing import Annotated

from fastapi import APIRouter, Depends

from medynium_api.core.session import AdminSession
from medynium_api.features.quality.schemas import GoldenRunList
from medynium_api.features.quality.service import QualityService

router = APIRouter(tags=["quality"])


def get_service() -> QualityService:
    return QualityService()


@router.get("/admin/golden-runs")
def golden_runs(
    admin: AdminSession, service: Annotated[QualityService, Depends(get_service)]
) -> GoldenRunList:
    """The latest stored golden run with every question's result, and earlier runs. Admins only."""
    return service.golden_runs(admin)
