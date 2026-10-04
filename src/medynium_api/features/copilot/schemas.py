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
    last_answer_id: str | None = Field(
        default=None,
        max_length=40,
        description="The previous answer in this conversation. Its drug and lab names (a closed vocabulary, never free text) help the planner resolve words like 'that medicine'.",
    )
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


class ProposalResult(BaseModel):
    """An approved proposal: where the new record is."""

    proposal_id: str
    patient_id: str
    record_id: str | None = None
    tab: str = "overview"
    status: Literal["approved"] = "approved"


class ProposalDiscarded(BaseModel):
    proposal_id: str
    status: Literal["discarded"] = "discarded"


class AskResult(BaseModel):
    """JSON mode (Accept: application/json): the final outcome of a request that would otherwise stream."""

    routes: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    proposals: list[dict[str, Any]] = Field(default_factory=list)
    answer: dict[str, Any] | None
    refusal: dict[str, Any] | None
    steps: list[dict[str, Any]]
    audit_id: str | None
