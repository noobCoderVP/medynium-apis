from typing import Any

from fastapi import APIRouter

from medynium_api.core.errors import not_implemented
from medynium_api.core.session import CurrentSession

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", summary="Three widgets from precomputed views, no AI call (Slice 3)")
def dashboard(session: CurrentSession) -> dict[str, Any]:
    raise not_implemented("GET /dashboard")


@router.get("/dashboard/briefing", summary="Agent briefing, on request only (P1)")
def briefing(session: CurrentSession) -> dict[str, Any]:
    raise not_implemented("GET /dashboard/briefing")
