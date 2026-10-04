import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from medynium_api.core.pagination import Paging, SortOrder
from medynium_api.core.session import CurrentSession
from medynium_api.features.audit.schemas import AiMetrics, AuditPage
from medynium_api.features.audit.service import AuditService

router = APIRouter(tags=["audit"])


def get_service() -> AuditService:
    return AuditService()


Service = Annotated[AuditService, Depends(get_service)]


@router.get("/audit")
def audit(
    session: CurrentSession,
    service: Service,
    page: Paging,
    patient_id: str | None = None,
    from_: Annotated[dt.date | None, Query(alias="from")] = None,
    to: dt.date | None = None,
    action: str | None = None,
    outcome: str | None = None,
    q: str | None = None,
    sort: Literal["when", "action", "outcome"] = "when",
    order: SortOrder = "desc",
) -> AuditPage:
    """The caller's own entries, newest first. Denied attempts are included."""
    return service.entries(session, patient_id, from_, to, action, outcome, q, sort, order, page)


@router.get("/audit/summary")
def audit_summary(
    session: CurrentSession, service: Service, days: Annotated[int, Query(ge=1, le=90)] = 7
) -> AiMetrics:
    """What the assistant did for the caller over the last days: volume, routes, models, tools chosen, how long people
    waited (median and 95th percentile) and the slowest steps. The caller's own entries only."""
    return service.metrics(session, days)
