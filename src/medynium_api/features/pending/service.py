"""What is waiting for this clinician: open findings, follow-ups that are due, abnormal results nobody has reviewed,
and recent emergency visits, across the patients they are entitled to (production plan Phase 3).

The Pending page and the assistant's `pending_work` tool read the same view, so they cannot disagree. Marking a lab
reviewed is a person's act: it is a write, it is audited, and the assistant has no way to do it."""

import datetime as dt
import time

from medynium_api.core.access import require_patient
from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.config import Settings
from medynium_api.core.errors import ApiError, not_found
from medynium_api.core.pagination import PageParams
from medynium_api.core.security.ratelimit import write_limiter
from medynium_api.core.session import Session
from medynium_api.core.snowflake.queries import Row
from medynium_api.core.snowflake.timing import pad
from medynium_api.features.pending.repository import PendingRepository
from medynium_api.features.pending.schemas import (
    LabReviewed,
    PendingItem,
    PendingPage,
    PendingSummary,
)


def _item(row: Row, as_of: dt.date) -> PendingItem:
    due = row["due_date"]
    return PendingItem(
        item_id=row["item_id"], patient_id=row["patient_id"], patient_name=row["patient_name"],
        kind=row["kind"], title=row["title"], detail=row["detail"], due_date=due,
        overdue=row["kind"] == "FOLLOW_UP" and due is not None and due <= as_of,
        raised_at=row["raised_at"], source_table=row["source_table"], source_id=row["source_id"],
    )  # fmt: skip


class PendingService:
    def __init__(self, settings: Settings, repo: PendingRepository | None = None) -> None:
        self.settings = settings
        self.repo = repo or PendingRepository()

    def page(
        self, session: Session, kinds: list[str] | None, patient_id: str | None, paging: PageParams
    ) -> PendingPage:
        if patient_id:
            require_patient(session, patient_id)
        as_of = dt.date.fromisoformat(self.settings.as_of_iso)
        rows, total = self.repo.page(
            session.snowflake_role, kinds, patient_id, paging.limit, paging.offset
        )
        return PendingPage(
            items=[_item(r, as_of) for r in rows], total=total, limit=paging.limit,
            offset=paging.offset, as_of=as_of,
        )  # fmt: skip

    def summary(self, session: Session) -> PendingSummary:
        by_kind = self.repo.counts(session.snowflake_role)
        return PendingSummary(
            total=sum(by_kind.values()),
            overdue=self.repo.overdue(session.snowflake_role, self.settings.as_of_iso),
            by_kind=by_kind,
            as_of=dt.date.fromisoformat(self.settings.as_of_iso),
        )

    def review_lab(self, session: Session, patient_id: str, lab_id: str) -> LabReviewed:
        write_limiter.check(session.user_id)
        started = time.monotonic()
        action = "REVIEW_LAB"
        try:
            require_patient(session, patient_id)
            if not self.repo.lab_is_pending_for(session.snowflake_role, patient_id, lab_id):
                raise not_found()
        except ApiError:
            write_audit(
                session,
                AuditEntry(
                    action=action,
                    patient_id=patient_id,
                    outcome="DENIED",
                    cost_note="no model call",
                ),
            )
            pad(started)
            raise
        row = self.repo.mark_reviewed(session.snowflake_role, session.user_id, patient_id, lab_id)
        write_audit(
            session,
            AuditEntry(
                action=action,
                patient_id=patient_id,
                cost_note="no model call",
                outcome_detail=lab_id,
            ),
            strict=True,
        )
        return LabReviewed(
            lab_id=row["lab_id"], patient_id=row["patient_id"], reviewed_at=row["reviewed_at"]
        )
