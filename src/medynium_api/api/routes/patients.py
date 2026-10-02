"""Patient endpoints. A denied patient returns the same 404 as a missing one (SEC-05)."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse

from medynium_api.core.errors import not_implemented
from medynium_api.core.session import CurrentSession

router = APIRouter(tags=["patients"])


@router.get("/patients", summary="Entitled worklist; search by q")
def list_patients(session: CurrentSession, q: str | None = None) -> list[dict[str, Any]]:
    raise not_implemented("GET /patients")


@router.get("/patients/{patient_id}", summary="Patient 360 overview")
def get_patient(patient_id: str, session: CurrentSession) -> dict[str, Any]:
    raise not_implemented("GET /patients/{id}")


@router.get("/patients/{patient_id}/timeline", summary="Merged timeline, date-range filter")
def timeline(
    patient_id: str,
    session: CurrentSession,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> list[dict[str, Any]]:
    raise not_implemented("GET /patients/{id}/timeline")


@router.get("/patients/{patient_id}/labs/{code}/trend", summary="Lab trend")
def lab_trend(patient_id: str, code: str, session: CurrentSession) -> dict[str, Any]:
    raise not_implemented("GET /patients/{id}/labs/{code}/trend")


@router.get("/patients/{patient_id}/claims", summary="Claims and utilization")
def claims(patient_id: str, session: CurrentSession) -> dict[str, Any]:
    raise not_implemented("GET /patients/{id}/claims")


@router.post(
    "/patients/{patient_id}/safety-review",
    summary="Hybrid safety review; streams steps over SSE and ends with answer_id (Slice 5)",
    response_class=EventSourceResponse,
)
def safety_review(patient_id: str, session: CurrentSession) -> None:
    raise not_implemented("POST /patients/{id}/safety-review")
