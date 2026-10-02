from typing import Any

from fastapi import APIRouter

from medynium_api.core.errors import not_implemented
from medynium_api.core.session import CurrentSession

router = APIRouter(tags=["audit"])


@router.get("/audit", summary="The caller's own audit entries (Slice 8)")
def audit(session: CurrentSession) -> list[dict[str, Any]]:
    raise not_implemented("GET /audit")
