"""The tool registry (agentic upgrade, phase A): every route resolves to a registered read tool."""

import pytest

from medynium_api.features.copilot.handlers import Ctx
from medynium_api.features.copilot.panel_plan import TOOLS as PANEL_TOOLS
from medynium_api.features.copilot.routing import Step
from medynium_api.features.copilot.tools import REGISTRY, describe, get
from medynium_api.features.copilot.tools.resolve import resolve


def _ctx(route: str, question: str) -> Ctx:
    return Ctx(None, None, "P1", question, Step(route=route), None, None, None, None)  # type: ignore[arg-type]


def test_registry_has_every_panel_tool_and_the_core_read_tools() -> None:
    get("search_labels")
    assert set(PANEL_TOOLS) <= set(REGISTRY)
    assert {"get_patient_record", "detect_changes", "query_structured", "run_safety_review"} <= set(
        REGISTRY
    )


def test_every_tool_describes_itself_for_the_planner() -> None:
    tools = describe()
    assert len({t["name"] for t in tools}) == len(tools)
    assert all(t["description"] and t["args"] for t in tools)


@pytest.mark.parametrize(
    ("route", "question", "tool"),
    [
        ("lookup", "what medications is she taking", "get_patient_record"),
        ("lookup", "what changed since the last visit", "detect_changes"),
        ("lookup", "how old is she", "query_structured"),
        ("analyst", "what's new since her previous visit", "detect_changes"),
        ("analyst", "how many days between her appointments", "query_structured"),
        ("knowledge", "warnings for metformin", "search_labels"),
        ("panel", "who are my patients", "list_my_patients"),
        ("safety", "anything concerning", "run_safety_review"),
    ],
)
def test_routes_resolve_to_the_same_handlers_as_before(
    route: str, question: str, tool: str
) -> None:
    assert resolve(_ctx(route, question)).name == tool


def test_lookup_kind_is_passed_to_the_record_tool() -> None:
    ctx = _ctx("lookup", "what medications is she taking")
    resolve(ctx)
    assert ctx.step.params["kind"] == "MEDS"


def test_no_registered_tool_writes() -> None:
    assert all(
        t.group in {"patient", "query", "change", "safety", "knowledge", "panel"}
        for t in REGISTRY.values()
    )
