"""Request and response models: the public API contract the UI types are generated from."""

from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthSnowflake(BaseModel):
    configured: bool
    database: str
    warehouse: str


class HealthResponse(BaseModel):
    """Never contains credentials (NFR-08). Role and agent status arrive with sign-in."""

    status: Literal["ok", "degraded"]
    version: str
    environment: str
    snowflake: HealthSnowflake
    agent_configured: bool


class LoginRequest(BaseModel):
    username: str = Field(examples=["SHARMA_DR"])
    password: str


class MeResponse(BaseModel):
    username: str
    display_name: str
    role: Literal["MED_DOCTOR", "MED_ASSISTANT"]


class Screen(StrEnum):
    DASHBOARD = "dashboard"
    PATIENTS = "patients"
    PATIENT = "patient"
    KNOWLEDGE = "knowledge"
    ACTIVITY = "activity"
    ADMIN = "admin"


class CopilotAskRequest(BaseModel):
    """Free text from the command bar or agent panel. Only this is routed (plan section 4.2)."""

    question: str = Field(min_length=1, max_length=2000)
    screen: Screen
    patient_id: str | None = None


class AgentActionName(StrEnum):
    """The closed allowlist (SEC-12). Anything else is rejected with `action_not_allowed`."""

    OPEN_PATIENT = "open_patient"
    SHOW_TIMELINE = "show_timeline"
    RUN_SAFETY_REVIEW = "run_safety_review"
    PIN_EVIDENCE = "pin_evidence"


class AgentActionRequest(BaseModel):
    action: str = Field(description="Validated against AgentActionName on the server.")
    params: dict[str, Any] = Field(default_factory=dict)


class TimelineQuery(BaseModel):
    from_: date | None = Field(default=None, alias="from")
    to: date | None = None


class ViewPreviewRequest(BaseModel):
    kind: Literal["saved_view", "visit_brief"]
    patient_id: str
    content: dict[str, Any]


class ViewSaveRequest(ViewPreviewRequest):
    approved: bool = Field(description="Must be true; the agent can never save on its own (FR-22).")
