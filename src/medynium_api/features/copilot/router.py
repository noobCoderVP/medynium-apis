"""Copilot endpoints. Send `Accept: text/event-stream` for a live stream (events in docs/api/README.md); any other
Accept runs to completion and returns the final object, which is what tests and the golden run use."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.errors import ErrorBody
from medynium_api.core.evidence.models import AnswerObject
from medynium_api.core.session import CurrentSession
from medynium_api.core.streaming import Run, collect, stream_response
from medynium_api.features.copilot.ports import Ports
from medynium_api.features.copilot.schemas import (
    ActionRequest,
    ActionResponse,
    AskRequest,
    AskResult,
    ProposalDiscarded,
    ProposalResult,
)
from medynium_api.features.copilot.service import CopilotService

router = APIRouter(
    tags=["copilot"],
    responses={404: {"model": ErrorBody}, 429: {"model": ErrorBody}, 503: {"model": ErrorBody}},
)


def get_ports() -> Ports:
    """Replaced at startup by medynium_api.wiring (a feature never imports another feature)."""
    raise RuntimeError("copilot ports are not wired")


def get_service(
    settings: Annotated[Settings, Depends(get_settings)],
    ports: Annotated[Ports, Depends(get_ports)],
) -> CopilotService:
    return CopilotService(settings, ports)


Service = Annotated[CopilotService, Depends(get_service)]
STREAM: dict[int | str, dict[str, Any]] = {
    200: {
        "content": {"text/event-stream": {}},
        "description": "Server-sent events: route, step, action, answer, refusal, error, done",
    }
}


def wants_stream(request: Request) -> bool:
    return "text/event-stream" in request.headers.get("accept", "")


@router.post("/patients/{patient_id}/safety-review", response_model=AnswerObject, responses=STREAM)
def safety_review(
    patient_id: str, request: Request, session: CurrentSession, service: Service
) -> Any:
    """Run the safety review for one patient (the manual button). 404 if the patient is missing or denied."""
    service.precheck(session, patient_id, None)
    if wants_stream(request):
        return stream_response(request, lambda run: service.safety_review(session, patient_id, run))
    run = collect(lambda run: service.safety_review(session, patient_id, run))
    return run.last("answer")


@router.post("/copilot/ask", response_model=AskResult, responses=STREAM)
def ask(body: AskRequest, request: Request, session: CurrentSession, service: Service) -> Any:
    """Route a free-text request and stream the result. The router sees no patient data; the server re-checks everything."""
    if body.patient_id:
        service.precheck(session, body.patient_id, body.question)

    def work(run: Run) -> None:
        service.ask(
            session,
            body.question,
            body.screen,
            body.patient_id,
            body.history,
            run,
            body.last_answer_id,
        )

    if wants_stream(request):
        return stream_response(request, work)
    run = collect(work)
    return AskResult(
        routes=[d for e, d in run.events if e == "route"],
        actions=[d for e, d in run.events if e == "action"],
        proposals=[d for e, d in run.events if e == "proposal"],
        answer=run.last("answer"),
        refusal=run.last("refusal"),
        steps=run.steps,
        audit_id=run.audit_id,
    )


@router.post("/agent/actions", responses={403: {"model": ErrorBody}, 409: {"model": ErrorBody}})
def agent_action(body: ActionRequest, session: CurrentSession, service: Service) -> ActionResponse:
    """Execute one allowlisted action under your own session. Anything else is refused, and the refusal is audited."""
    run = Run()
    result = service.action(session, body.action, body.params, run)
    return ActionResponse(action=body.action, result=result, audit_id=run.audit_id)


@router.post(
    "/agent/proposals/{proposal_id}/approve",
    responses={403: {"model": ErrorBody}, 409: {"model": ErrorBody}},
)
def approve_proposal(proposal_id: str, session: CurrentSession, service: Service) -> ProposalResult:
    """Write a change the assistant prepared, after the clinician approved its preview. Same service, same checks and
    audit as the manual screen. Doctors only; someone else's or an expired proposal is 404."""
    return ProposalResult.model_validate(service.approve_proposal(session, proposal_id))


@router.post("/agent/proposals/{proposal_id}/discard")
def discard_proposal(
    proposal_id: str, session: CurrentSession, service: Service
) -> ProposalDiscarded:
    """Drop a prepared change. Nothing was written."""
    return ProposalDiscarded.model_validate(service.discard_proposal(session, proposal_id))
