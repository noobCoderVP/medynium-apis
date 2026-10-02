from typing import Any

from fastapi import APIRouter

from medynium_api.core.errors import not_implemented
from medynium_api.core.session import CurrentSession
from medynium_api.schemas import ViewPreviewRequest, ViewSaveRequest

router = APIRouter(tags=["views"])


@router.post("/views/preview", summary="Preview a saved view or visit brief (P1)")
def preview(body: ViewPreviewRequest, session: CurrentSession) -> dict[str, Any]:
    raise not_implemented("POST /views/preview")


@router.post("/views", summary="Save after approval; needs approved=true (P1)")
def save(body: ViewSaveRequest, session: CurrentSession) -> dict[str, Any]:
    raise not_implemented("POST /views")
