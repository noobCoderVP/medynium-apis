---
name: access-check
description: Re-prove that the entitlement chain binds SQL, Cortex Analyst and the assistant (SEC-03, SEC-05, D6). Use after any change to policies, grants, roles, the semantic view or a patient-keyed table.
---

1. Run `poetry run poe db:check` and report any red check verbatim.
2. Run `poetry run pytest -m snowflake tests/integration/test_access_sql.py` (the assistant must see zero rows of P-1093 in every patient-keyed table, as the assistant's own role).
3. Run `poetry run pytest -m snowflake tests/integration/test_copilot.py -k "denied or refusal"` (denied equals missing: same 404 body, no patient ID in the message).
4. Run `poetry run poe eval:golden` and confirm the `access` group (G08 onward) passes.
5. For every new table with `PATIENT_ID`, confirm `SECURITY.APPLY_POLICIES()` covers it (snowflake/06_policies.sql) and the test in step 2 lists it.
6. Update the Q-A rows in `docs/quality/access-and-safety-matrix.md` only when a test result changed. Never relax a test to make it pass.
