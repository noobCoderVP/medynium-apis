"""Findings: a clinician's recorded decision on a safety-review statement (product plan E3).

The agent never creates or changes a finding; only a signed-in user does, one at a time, and each change is audited.
"""

import datetime as dt
from typing import Any

from medynium_api.core.access import require_patient
from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.errors import invalid, not_found
from medynium_api.core.ids import new_id
from medynium_api.core.session import Session
from medynium_api.features.findings.repository import FindingRepository
from medynium_api.features.findings.rules import check_update, is_open
from medynium_api.features.findings.schemas import (
    Colleague,
    ColleagueList,
    Finding,
    FindingCreate,
    FindingList,
    FindingUpdate,
)


def _audit(session: Session, patient_id: str, action: str, detail: str, answer_id: str) -> None:
    entry = AuditEntry(
        action=action,
        patient_id=patient_id,
        answer_id=answer_id,
        cost_note="no model call",
        outcome_detail=detail,
    )
    write_audit(session, entry, strict=True)


class FindingService:
    def __init__(self, repo: FindingRepository | None = None) -> None:
        self.repo = repo or FindingRepository()

    def _shape(self, rows: list[dict[str, Any]]) -> list[Finding]:
        ids = {v for r in rows for v in (r["assigned_to"], r["created_by"]) if v}
        names = self.repo.names(ids)
        return [
            Finding(
                finding_id=r["finding_id"], patient_id=r["patient_id"], answer_id=r["answer_id"],
                consideration_id=r["consideration_id"], summary=r["summary"], status=r["status"],
                reason=r["reason"], follow_up_on=r["follow_up_on"], assigned_to=r["assigned_to"],
                assigned_to_name=names.get(r["assigned_to"] or ""), created_by_name=names.get(r["created_by"]),
                created_at=r["created_at"], updated_at=r["updated_at"],
            )
            for r in rows
        ]  # fmt: skip

    def list_findings(self, session: Session, patient_id: str) -> FindingList:
        require_patient(session, patient_id)
        items = self._shape(self.repo.list_findings(session.snowflake_role, patient_id))
        return FindingList(items=items, open_count=sum(1 for f in items if is_open(f.status)))

    def colleagues(self, session: Session, patient_id: str) -> ColleagueList:
        require_patient(session, patient_id)
        return ColleagueList(
            items=[
                Colleague(user_id=r["user_id"], name=r["display_name"], role=r["role_code"])
                for r in self.repo.colleagues(patient_id)
                if r["user_id"] != session.user_id
            ]
        )

    def create(self, session: Session, patient_id: str, body: FindingCreate) -> Finding:
        require_patient(session, patient_id)
        role = session.snowflake_role
        existing = self.repo.existing(role, patient_id, body.answer_id, body.consideration_id)
        if existing:  # repeating the click returns the same finding, never a duplicate
            return self._shape([existing])[0]
        text = self.repo.statement(role, patient_id, body.answer_id, body.consideration_id)
        if not text:
            raise not_found()  # not the caller's answer, another patient's, or no such statement
        finding_id = new_id("FND", 8)
        row = self.repo.create(
            role,
            finding_id,
            patient_id,
            body.answer_id,
            body.consideration_id,
            text,
            session.user_id,
        )
        if row is None:
            raise not_found()
        _audit(session, patient_id, "RAISE_FINDING", f"{finding_id} raised", body.answer_id)
        return self._shape([row])[0]

    def update(self, session: Session, finding_id: str, body: FindingUpdate) -> Finding:
        row = self.repo.get(
            session.snowflake_role, finding_id
        )  # the policy hides other patients' findings
        if row is None:
            raise not_found()
        patient_id = row["patient_id"]
        require_patient(session, patient_id)
        colleagues = frozenset(r["user_id"] for r in self.repo.colleagues(patient_id))
        check_update(row["status"], body, session.user_id, dt.date.today(), colleagues)
        reopen = body.status in ("NEW", "ACKNOWLEDGED")
        reason = None if reopen else (body.reason or "").strip() or None
        follow_up = body.follow_up_on if body.status == "FLAGGED" else None
        assigned = body.assigned_to if body.status == "ESCALATED" else None
        updated = self.repo.update(
            session.snowflake_role,
            finding_id,
            body.status,
            reason,
            follow_up,
            assigned,
            session.user_id,
        )
        if updated is None:
            raise invalid("The finding could not be updated.")
        detail = f"{finding_id}: {row['status']} to {body.status}"
        _audit(session, patient_id, "DECIDE_FINDING", detail, row["answer_id"])
        return self._shape([updated])[0]
