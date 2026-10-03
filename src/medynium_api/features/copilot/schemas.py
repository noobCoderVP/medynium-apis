from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Screen = Literal["dashboard", "patients", "patient", "knowledge", "activity", "admin"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AskRequest(Strict):
    """Free text from the command bar or agent panel. Only this is routed. `patient_id` is the open patient and is
    never trusted as proof of access."""

    question: str = Field(min_length=1, max_length=2000)
    screen: Screen
    patient_id: str | None = Field(default=None, max_length=20)
    history: list[str] = Field(
        default_factory=list, max_length=2, description="The last two user questions (text only)."
    )


class ActionRequest(Strict):
    action: str = Field(
        max_length=40,
        description="One of open_patient, show_timeline, run_safety_review, pin_evidence.",
    )
    params: dict[str, Any] = Field(default_factory=dict)


class ActionResponse(BaseModel):
    action: str
    status: Literal["done"] = "done"
    result: dict[str, Any]
    audit_id: str | None


class AskResult(BaseModel):
    """JSON mode (Accept: application/json): the final outcome of a request that would otherwise stream."""

    routes: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    answer: dict[str, Any] | None
    refusal: dict[str, Any] | None
    steps: list[dict[str, Any]]
    audit_id: str | None
