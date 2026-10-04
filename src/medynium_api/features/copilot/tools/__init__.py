"""The tool registry (agentic upgrade, phase A). One place that names every read tool the assistant can use.

A tool is a name, a description the planner will read, an argument model, and a handler that takes the request
context and emits one answer. Handlers still run under the caller's role and never skip the server checks; the
registry only gives them a common shape so the planner (phase B) can pick from it and the audit can name them.
Nothing here writes the clinical record. Write tools arrive in phase B2 as proposals that need approval."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from medynium_api.core.evidence.models import AnswerObject
from medynium_api.core.streaming import Run
from medynium_api.features.copilot.agent_plan import AGENT_TOOLS, NoArgs
from medynium_api.features.copilot.handlers import Ctx

Group = Literal["patient", "query", "change", "safety", "knowledge", "panel"]
Handler = Callable[[Ctx, Run], AnswerObject | None]


@dataclass(frozen=True)
class Tool:
    name: str
    group: Group
    description: str
    args: type[BaseModel]
    handler: Handler
    patient_scoped: bool  # needs an open patient; the dispatcher refuses otherwise
    uses_model: bool = False


REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    if tool.name in REGISTRY:
        raise ValueError(f"duplicate tool {tool.name}")
    REGISTRY[tool.name] = tool
    return tool


def get(name: str) -> Tool:
    from medynium_api.features.copilot.tools import builtin  # noqa: F401  (registers on first use)

    return REGISTRY[name]


def describe(groups: set[str] | None = None) -> list[dict[str, Any]]:
    """What a planner prompt lists: name, group, description and the argument schema of each tool."""
    from medynium_api.features.copilot.tools import builtin  # noqa: F401

    return [
        {"name": t.name, "group": t.group, "description": t.description, "args": t.args.model_json_schema()}
        for t in REGISTRY.values()
        if groups is None or t.group in groups
    ]  # fmt: skip


__all__ = ["AGENT_TOOLS", "REGISTRY", "NoArgs", "Tool", "describe", "get", "register"]
