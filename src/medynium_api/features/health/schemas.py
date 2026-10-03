from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Liveness only. No configuration, no credentials (NFR-08)."""

    status: Literal["ok"] = "ok"
    version: str


class SnowflakeHealth(BaseModel):
    reachable: bool
    database: str
    warehouse: str
    warehouse_state: str | None = None
    service_role: str | None = None


class CortexHealth(BaseModel):
    router_model: str
    strong_model: str
    safety_path: str
    search_service: str


class HealthDetails(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    snowflake: SnowflakeHealth
    cortex: CortexHealth
    audit_writes: Literal["ok", "failing", "unknown"]
