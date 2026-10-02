from fastapi import APIRouter

from medynium_api import __version__
from medynium_api.core.config import get_settings
from medynium_api.schemas import HealthResponse, HealthSnowflake

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness and configuration status")
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.app_env,
        snowflake=HealthSnowflake(
            configured=settings.snowflake_configured,
            database=settings.snowflake_database,
            warehouse=settings.snowflake_warehouse,
        ),
        agent_configured=bool(settings.strong_model),
    )
