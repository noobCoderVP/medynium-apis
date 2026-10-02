from typing import Any

from fastapi import APIRouter, Query

from medynium_api.core.errors import not_implemented
from medynium_api.core.session import CurrentSession

router = APIRouter(tags=["knowledge"])


@router.get("/knowledge/search", summary="Label and guideline search with full citations (Slice 4)")
def search(session: CurrentSession, q: str = Query(min_length=1)) -> list[dict[str, Any]]:
    raise not_implemented("GET /knowledge/search")
