import datetime as dt

from medynium_api.core.pagination import PageParams
from medynium_api.core.session import Session
from medynium_api.core.snowflake.queries import json_value
from medynium_api.features.audit.repository import AuditRepository
from medynium_api.features.audit.schemas import AuditItem, AuditPage


class AuditService:
    def __init__(self, repo: AuditRepository | None = None) -> None:
        self.repo = repo or AuditRepository()

    def entries(
        self,
        session: Session,
        patient_id: str | None,
        start: dt.date | None,
        end: dt.date | None,
        action: str | None,
        outcome: str | None,
        q: str | None,
        sort: str | None,
        order: str,
        page: PageParams,
    ) -> AuditPage:
        rows, total = self.repo.list_entries(
            session.snowflake_role,
            patient_id,
            start,
            end,
            action,
            outcome,
            q,
            sort,
            order,
            page.limit,
            page.offset,
        )
        items = [
            AuditItem(
                audit_id=r["audit_id"],
                occurred_at=r["occurred_at"],
                via=r["via"],
                action=r["action"],
                route=r["route"],
                model=r["model"],
                confidence=float(r["confidence"]) if r["confidence"] is not None else None,
                cost_note=r["cost_note"],
                patient_id=r["patient_id"],
                question=r["question"],
                answer_id=r["answer_id"],
                patient_evidence_ids=json_value(r["patient_evidence_ids"]) or [],
                document_ids=json_value(r["document_ids"]) or [],
                steps=json_value(r["steps"]) or [],
                outcome=r["outcome"],
            )
            for r in rows
        ]
        return AuditPage(items=items, total=total, limit=page.limit, offset=page.offset)
