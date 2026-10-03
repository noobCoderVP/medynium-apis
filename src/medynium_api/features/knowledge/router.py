from typing import Annotated

from fastapi import APIRouter, Depends, Query

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.errors import ErrorBody
from medynium_api.core.session import CurrentSession
from medynium_api.features.knowledge.schemas import KnowledgeStatus, SearchResponse
from medynium_api.features.knowledge.service import KnowledgeService

router = APIRouter(tags=["knowledge"], responses={503: {"model": ErrorBody}})


def get_service(settings: Annotated[Settings, Depends(get_settings)]) -> KnowledgeService:
    return KnowledgeService(settings)


Service = Annotated[KnowledgeService, Depends(get_service)]


@router.get("/knowledge/search")
def search(
    session: CurrentSession,
    service: Service,
    q: Annotated[str, Query(min_length=2, max_length=300)],
    drug: Annotated[str | None, Query(max_length=80)] = None,
    section: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
) -> SearchResponse:
    """Label and guideline search with a full citation on every result. Brand names resolve to their generic."""
    return service.search(session, q, drug, section, limit)


@router.get("/knowledge/status")
def status(session: CurrentSession, service: Service) -> KnowledgeStatus:
    """Snapshot date, counts and the drugs in the index. The corpus is a controlled snapshot, not a live feed."""
    return service.status(session)
