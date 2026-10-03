"""The one audit writer (FR-10, ADR-013). Every route and action uses it, denials included.

Audit rows are inserted synchronously so a crash cannot lose a denial or an agent action. Account events go
to SECURITY.AUTH_EVENT under the service role; Copilot and action events go to ANALYTICS.COPILOT_AUDIT under
the caller's own role (insert only; the own-rows policy applies to reads).
"""

import json
from dataclasses import dataclass, field
from typing import Any

import structlog

from medynium_api.core.ids import new_id, new_uuid
from medynium_api.core.session import Session
from medynium_api.core.snowflake.queries import execute
from medynium_api.core.snowflake.role_session import service_cursor, user_cursor

log = structlog.get_logger()


@dataclass
class AuditEntry:
    action: str
    outcome: str = "OK"
    via: str = "USER"
    route: str | None = None
    model: str | None = None
    confidence: float | None = None
    cost_note: str | None = None
    patient_id: str | None = None
    question: str | None = None
    answer_id: str | None = None
    patient_evidence_ids: list[str] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    prompt_hash: str | None = None
    outcome_detail: str | None = None


def write_audit(session: Session, entry: AuditEntry, *, strict: bool = False) -> str:
    """Insert one COPILOT_AUDIT row. With strict=False a write failure is logged, not raised."""
    audit_id = new_id("AUD", 10)
    try:
        with user_cursor(session.snowflake_role) as cur:
            execute(
                cur,
                "INSERT INTO ANALYTICS.COPILOT_AUDIT (AUDIT_ID, OCCURRED_AT, USER_ID, ROLE_CODE, VIA, ACTION, ROUTE, "
                "MODEL, CONFIDENCE, COST_NOTE, PATIENT_ID, QUESTION, ANSWER_ID, PATIENT_EVIDENCE_IDS, DOCUMENT_IDS, "
                "STEPS, PROMPT_HASH, OUTCOME, OUTCOME_DETAIL) "
                "SELECT %s, SYSDATE(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, PARSE_JSON(%s), PARSE_JSON(%s), "
                "PARSE_JSON(%s), %s, %s, %s",
                (
                    audit_id, session.user_id, session.role, entry.via, entry.action, entry.route, entry.model,
                    entry.confidence, entry.cost_note, entry.patient_id, entry.question, entry.answer_id,
                    json.dumps(entry.patient_evidence_ids), json.dumps(entry.document_ids), json.dumps(entry.steps),
                    entry.prompt_hash, entry.outcome, entry.outcome_detail,
                ),
            )  # fmt: skip
    except Exception as exc:
        log.error("audit_write_failed", action=entry.action, exc_type=type(exc).__name__)
        if strict:
            raise
    return audit_id


def write_auth_event(
    event_type: str,
    *,
    user_id: str | None = None,
    actor_id: str | None = None,
    email_attempted: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Insert one SECURITY.AUTH_EVENT row (sign-ins, invites, password and entitlement changes)."""
    try:
        with service_cursor() as cur:
            execute(
                cur,
                "INSERT INTO SECURITY.AUTH_EVENT (EVENT_ID, EVENT_AT, EVENT_TYPE, USER_ID, ACTOR_ID, EMAIL_ATTEMPTED, "
                "IP_ADDRESS, USER_AGENT, DETAIL) SELECT %s, SYSDATE(), %s, %s, %s, %s, %s, %s, PARSE_JSON(%s)",
                (new_uuid(), event_type, user_id, actor_id, email_attempted, ip_address, user_agent,
                 json.dumps(detail or {})),
            )  # fmt: skip
    except Exception as exc:
        log.error("auth_event_failed", event_type=event_type, exc_type=type(exc).__name__)
