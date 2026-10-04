from typing import Annotated

from fastapi import APIRouter, Depends, Query

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.errors import ErrorBody
from medynium_api.core.session import CurrentSession
from medynium_api.features.similar.schemas import SimilarResponse
from medynium_api.features.similar.service import SimilarService

router = APIRouter(tags=["similar"], responses={404: {"model": ErrorBody}})


def get_service(settings: Annotated[Settings, Depends(get_settings)]) -> SimilarService:
    return SimilarService(settings)


Service = Annotated[SimilarService, Depends(get_service)]


@router.get("/patients/{patient_id}/similar")
def similar_patients(
    patient_id: str,
    session: CurrentSession,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
) -> SimilarResponse:
    """The closest of the caller's own patients to this one, each with the reasons. For comparison only; a ranking
    aid, never a prediction or a recommendation. Only patients the caller can already open can appear."""
    return service.find(session, patient_id, limit)
