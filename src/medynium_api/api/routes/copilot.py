"""Copilot (routed free text) and the allowlisted agent actions (plan section 4, Slices 6 and 7)."""

from typing import Any

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from medynium_api.core.errors import not_implemented
from medynium_api.core.session import CurrentSession
from medynium_api.schemas import AgentActionRequest, CopilotAskRequest

router = APIRouter(tags=["copilot"])


@router.post(
    "/copilot/ask",
    summary="Route a free-text request and stream the result over SSE (Slice 6)",
    response_class=EventSourceResponse,
)
def ask(body: CopilotAskRequest, session: CurrentSession) -> None:
    raise not_implemented("POST /copilot/ask")


@router.post("/agent/actions", summary="Execute one allowlisted action (Slice 7)")
def agent_action(body: AgentActionRequest, session: CurrentSession) -> dict[str, Any]:
    raise not_implemented("POST /agent/actions")
