"""Doctor-only. Role enforcement is added with the first real implementation."""

from typing import Any

from fastapi import APIRouter

from medynium_api.core.errors import not_implemented
from medynium_api.core.session import CurrentSession

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/golden-run", summary="Run the golden-question report (Slice 9)")
def golden_run(session: CurrentSession) -> dict[str, Any]:
    raise not_implemented("POST /admin/golden-run")


@router.post("/skills/{name}", summary="Run a scoped CoCo skill (P1)")
def run_skill(name: str, session: CurrentSession) -> dict[str, Any]:
    raise not_implemented("POST /admin/skills/{name}")
