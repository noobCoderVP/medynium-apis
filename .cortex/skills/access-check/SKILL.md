---
name: access-check
description: Prove that entitlement holds for Medynium. Use after any change to roles, row access policies, the write path or a new endpoint.
---

1. `poetry run python scripts/db.py check` (policy coverage, grants, procedures) must be green.
2. Per file, run the live tests: `poetry run pytest tests/integration/test_access.py tests/integration/test_records.py -m snowflake`.
3. Confirm a denied patient returns the same 404 body as a missing one, with no patient id in the message.
4. Confirm no runtime path uses MED_ADMIN and requests run under the user's own `U_` role (writes go through MED_CLINICAL_WRITER procedures that re-check the entitlement).
5. Summarise as a matrix: role, action, expected, actual. Update `docs/quality/access-and-safety-matrix.md` only from observed results.
