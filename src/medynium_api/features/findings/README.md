# findings

**Purpose:** A clinician's recorded decision on a safety-review statement: acknowledge, flag for follow-up, dismiss with a reason, or escalate to a colleague who has the patient. Only a signed-in user creates or changes one; the agent cannot.
**Endpoints:** GET/POST /patients/{id}/findings, GET /patients/{id}/colleagues, PATCH /findings/{id}
**Requirements:** FR-22 spirit (a person decides, nothing is automatic); product plan E3
**Rules:** `rules.py` holds what each decision requires (tested without a database). Every raise and decision writes an audit row (`RAISE_FINDING`, `DECIDE_FINDING`). `ANALYTICS.FINDING` carries `PATIENT_RAP`, so findings are visible to everyone entitled to the patient and to no one else.
**May import:** `core/` only, never another feature.
**Status:** built. Needs `db.py apply 05`, `06` and `60` before it works against Snowflake. Unit tests pass; live tests not yet written or run.
