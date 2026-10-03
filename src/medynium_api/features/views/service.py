"""Preview, approve, save (FR-22, P1). A preview lives in memory for 10 minutes and writes nothing."""

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from medynium_api.core.access import require_patient
from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.errors import invalid, not_found
from medynium_api.core.ids import new_id
from medynium_api.core.session import Session
from medynium_api.core.snowflake.queries import json_value
from medynium_api.features.views.repository import ViewRepository
from medynium_api.features.views.schemas import (
    SavedView,
    ViewPreview,
    ViewPreviewRequest,
    ViewSaveRequest,
)

PREVIEW_SECONDS = 600
_previews: dict[str, tuple[float, str, ViewPreview]] = {}
_lock = threading.Lock()


def _view(row: dict[str, Any]) -> SavedView:
    return SavedView(
        view_id=row["view_id"], kind=row["kind"], patient_id=row["patient_id"], title=row["title"],
        content=json_value(row["content"]) or {}, approved_at=row["approved_at"], created_at=row["created_at"],
    )  # fmt: skip


class ViewService:
    def __init__(self, repo: ViewRepository | None = None) -> None:
        self.repo = repo or ViewRepository()

    def preview(self, session: Session, body: ViewPreviewRequest) -> ViewPreview:
        require_patient(session, body.patient_id)
        title = str(
            body.content.get("title")
            or ("Visit brief" if body.kind == "VISIT_BRIEF" else "Saved view")
        )[:120]
        expires = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=PREVIEW_SECONDS)
        preview = ViewPreview(
            preview_id=new_id("PV", 8), kind=body.kind, patient_id=body.patient_id, title=title,
            content=body.content, expires_at=expires,
        )  # fmt: skip
        with _lock:
            now = time.monotonic()
            for key in [k for k, (until, _, _) in _previews.items() if until < now]:
                del _previews[key]
            _previews[preview.preview_id] = (now + PREVIEW_SECONDS, session.user_id, preview)
        return preview

    def save(self, session: Session, body: ViewSaveRequest) -> SavedView:
        if not body.approved:
            raise invalid(
                "Approve the preview to save it.",
                [{"field": "approved", "problem": "must be true"}],
            )
        with _lock:
            entry = _previews.pop(body.preview_id, None)
        if entry is None or entry[0] < time.monotonic() or entry[1] != session.user_id:
            raise not_found()
        preview = entry[2]
        require_patient(session, preview.patient_id)
        row = self.repo.save(
            session.snowflake_role, new_id("VW", 8), session.user_id, preview.patient_id, preview.kind,
            preview.title, preview.content,
        )  # fmt: skip
        if row is None:
            raise not_found()
        write_audit(
            session,
            AuditEntry(
                action="SAVE_VIEW", patient_id=preview.patient_id, cost_note="no model call"
            ),
        )
        return _view(row)

    def list_views(self, session: Session, patient_id: str | None) -> list[SavedView]:
        if patient_id:
            require_patient(session, patient_id)
        return [_view(r) for r in self.repo.list_views(session.snowflake_role, patient_id)]
