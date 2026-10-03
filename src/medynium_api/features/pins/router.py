from typing import Annotated

from fastapi import APIRouter, Depends, Header

from medynium_api.core.errors import ErrorBody
from medynium_api.core.session import CurrentSession
from medynium_api.features.pins.schemas import Pin, PinCreate, PinList
from medynium_api.features.pins.service import PinService

router = APIRouter(tags=["pins"], responses={404: {"model": ErrorBody}})


def get_service() -> PinService:
    return PinService()


Service = Annotated[PinService, Depends(get_service)]


@router.get("/patients/{patient_id}/pins")
def list_pins(patient_id: str, session: CurrentSession, service: Service) -> PinList:
    """Evidence the caller pinned to this patient's workspace."""
    return service.list_pins(session, patient_id)


@router.post("/patients/{patient_id}/pins", status_code=201)
def create_pin(
    patient_id: str,
    body: PinCreate,
    session: CurrentSession,
    service: Service,
    idempotency_key: Annotated[str | None, Header(max_length=100)] = None,
) -> Pin:
    """Pin one evidence item from one of the caller's own answers. Repeats with the same key return the same pin."""
    return service.create(session, patient_id, body, idempotency_key)


@router.delete("/patients/{patient_id}/pins/{pin_id}", status_code=204)
def delete_pin(patient_id: str, pin_id: str, session: CurrentSession, service: Service) -> None:
    service.delete(session, patient_id, pin_id)
