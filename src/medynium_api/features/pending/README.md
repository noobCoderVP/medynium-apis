# pending

**Purpose:** What is waiting for this clinician across the patients they are entitled to: findings that are open, escalated or due for follow-up, abnormal results nobody has reviewed, and recent emergency visits. One view (`ANALYTICS.PENDING_ITEM`, snowflake/09_pending_work.sql) feeds the Pending page, the navigation badge, the dashboard and the assistant's `pending_work` tool, so they cannot disagree.
**Endpoints:** GET /pending, GET /pending/summary, POST /patients/{id}/labs/{lab_id}/review
**Requirements:** production plan Phase 3 (P3.1, P3.5); AI-10 (manual parity)
**Rules:** read under the caller's own role, so the entitled-patient policy decides what appears. Marking a lab reviewed is a doctor's act, audited as `REVIEW_LAB`, and is the only write; the assistant cannot do it. A denied patient is audited and answered like a missing one. Follow-ups are marked overdue against the as-of date.
**May import:** `core/` only, never another feature. The SQL it shares with the assistant lives in `core/panel_sql.py`.
**Status:** built; live tests in `tests/integration/test_pending.py`.
