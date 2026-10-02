from typing import Any

from fastapi import APIRouter

from medynium_api.core.errors import not_implemented
from medynium_api.core.session import CurrentSession

router = APIRouter(tags=["evidence"])


@router.get("/evidence/{answer_id}", summary="Why? panel data for one answer (Slice 5)")
def get_evidence(answer_id: str, session: CurrentSession) -> dict[str, Any]:
    raise not_implemented("GET /evidence/{answer_id}")
