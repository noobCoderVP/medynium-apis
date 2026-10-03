from typing import Annotated

from fastapi import APIRouter, Depends

from medynium_api.core.errors import ErrorBody
from medynium_api.core.session import CurrentSession
from medynium_api.features.views.schemas import (
    SavedView,
    ViewPreview,
    ViewPreviewRequest,
    ViewSaveRequest,
)
from medynium_api.features.views.service import ViewService

router = APIRouter(tags=["views"], responses={404: {"model": ErrorBody}})


def get_service() -> ViewService:
    return ViewService()


Service = Annotated[ViewService, Depends(get_service)]


@router.post("/views/preview")
def preview(body: ViewPreviewRequest, session: CurrentSession, service: Service) -> ViewPreview:
    """Preview a saved view or visit brief. Nothing is stored (P1)."""
    return service.preview(session, body)


@router.post("/views", status_code=201)
def save(body: ViewSaveRequest, session: CurrentSession, service: Service) -> SavedView:
    """Save an approved preview. `approved` must be true; the agent can never save on its own."""
    return service.save(session, body)


@router.get("/views")
def list_views(
    session: CurrentSession, service: Service, patient_id: str | None = None
) -> list[SavedView]:
    return service.list_views(session, patient_id)
