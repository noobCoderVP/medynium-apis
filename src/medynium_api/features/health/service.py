from medynium_api import __version__
from medynium_api.core.config import Settings
from medynium_api.features.health.repository import HealthRepository
from medynium_api.features.health.schemas import (
    CortexHealth,
    HealthDetails,
    HealthResponse,
    SnowflakeHealth,
)


class HealthService:
    def __init__(self, settings: Settings, repo: HealthRepository | None = None) -> None:
        self.settings = settings
        self.repo = repo or HealthRepository()

    def liveness(self) -> HealthResponse:
        return HealthResponse(version=__version__)

    def details(self) -> HealthDetails:
        s = self.settings
        reachable, role, state, audit = False, None, None, "unknown"
        try:
            ident, wh = self.repo.probe(s.snowflake_warehouse)
            reachable = ident is not None
            role = ident["role_name"] if ident else None
            state = wh["state"] if wh else None
            audit = "ok" if self.repo.audit_table_writable() else "failing"
        except Exception:
            reachable, audit = False, "failing"
        return HealthDetails(
            status="ok" if reachable and audit == "ok" else "degraded",
            version=__version__,
            environment=s.app_env,
            snowflake=SnowflakeHealth(
                reachable=reachable,
                database=s.snowflake_database,
                warehouse=s.snowflake_warehouse,
                warehouse_state=state,
                service_role=role,
            ),
            cortex=CortexHealth(
                router_model=s.router_model,
                strong_model=s.strong_model,
                safety_path=s.safety_path,
                search_service=s.cortex_search_service,
            ),
            audit_writes="ok" if audit == "ok" else "failing" if audit == "failing" else "unknown",
        )
