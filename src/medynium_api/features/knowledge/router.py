from typing import Annotated

from fastapi import APIRouter, Depends, Query

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.errors import ErrorBody
from medynium_api.core.session import CurrentSession
from medynium_api.features.knowledge.schemas import DrugDirectory, KnowledgeStatus, SearchResponse
from medynium_api.features.knowledge.service import KnowledgeService

router = APIRouter(tags=["knowledge"], responses={503: {"model": ErrorBody}})


def get_service(settings: Annotated[Settings, Depends(get_settings)]) -> KnowledgeService:
    return KnowledgeService(settings)


Service = Annotated[KnowledgeService, Depends(get_service)]


@router.get("/knowledge/search")
def search(
    session: CurrentSession,
    service: Service,
    q: Annotated[str | None, Query(min_length=2, max_length=300)] = None,
    drug: Annotated[str | None, Query(max_length=80)] = None,
    section: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
) -> SearchResponse:
    """Label search with a full citation on every result. Brand names and small typos resolve to the generic.

    Give `q`, a `drug`, or both. A drug without `q` lists that drug's sections. `section` takes a heading in any case,
    or a word from it ("warnings").
    """
    return service.search(session, q, drug, section, limit)


@router.get("/knowledge/status")
def status(session: CurrentSession, service: Service) -> KnowledgeStatus:
    """Snapshot date, counts and the drugs in the index. The corpus is a controlled snapshot, not a live feed."""
    return service.status(session)


@router.get("/knowledge/drugs")
def drugs(session: CurrentSession, service: Service) -> DrugDirectory:
    """Every indexed drug with its Indian brands and section count, for browsing and filtering."""
    return service.drugs(session)
