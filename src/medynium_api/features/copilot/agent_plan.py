"""What an agent step may ask for: the combinable read tools and their argument models, checked before anything runs.
Kept apart from the tool handlers so routing can validate a plan without importing them."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# Read tools the agent route may combine (one patient in scope). The safety review is a whole answer on its own, and
# panel tools span patients, so neither is combined here.
AGENT_TOOLS = (
    "get_patient_record", "detect_changes", "query_structured", "search_labels", "get_attention", "get_gaps", "read_report",
)  # fmt: skip
MAX_TOOLS = 3


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(Strict):
    pass


class RecordArgs(Strict):
    kind: Literal["MEDS", "LABS", "UTIL", "SUMMARY"]


class ChangeArgs(Strict):
    since: Literal["90d", "1y"] | None = None  # left out: since the previous visit


class ReportArgs(Strict):
    report: str | None = Field(
        default=None, max_length=120
    )  # a file name or report id; left out: the latest
    query: str | None = Field(default=None, max_length=200)  # what to look for in its pages


class LabArgs(Strict):
    drug: str = Field(min_length=3, max_length=40)


class LabelArgs(Strict):
    query: str | None = Field(default=None, max_length=200)


class AnalystArgs(Strict):
    question: str | None = Field(default=None, max_length=300)


ARGS: dict[str, type[BaseModel]] = {
    "get_patient_record": RecordArgs,
    "detect_changes": ChangeArgs,
    "get_attention": NoArgs,
    "get_gaps": NoArgs,
    "read_report": ReportArgs,
    "query_structured": AnalystArgs,
    "search_labels": LabelArgs,
}


def validate_agent_tools(params: dict[str, Any]) -> list[tuple[str, dict[str, Any]]] | None:
    """The tools an agent step asks for, checked against the closed list and each tool's argument model."""
    raw = params.get("tools")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_TOOLS:
        return None
    checked: list[tuple[str, dict[str, Any]]] = []
    for item in raw:
        name = item.get("tool") if isinstance(item, dict) else None
        if name not in ARGS:
            return None
        try:
            args = ARGS[name].model_validate(item.get("args") or {}).model_dump(exclude_none=True)
        except (ValidationError, TypeError):
            return None
        checked.append((name, args))
    return checked
