# snowflake/

Idempotent setup SQL, numbered in run order. `00_bootstrap.sql` and `00_bootstrap_writer.sql` are run by a person as ACCOUNTADMIN (`scripts/db.py bootstrap`, `bootstrap-writer`); the rest run as `MED_ADMIN` through `poetry run python scripts/db.py apply [NN]`. Nothing here is executed by the deployed API.

| Files | What |
| --- | --- |
| 01 to 05 | schemas, roles, security, clinical, knowledge and analytics tables |
| 06 | row access policies (`SECURITY.APPLY_POLICIES()` re-applies them to every patient table) |
| 07, 08 | procedures; 08 is the write path: role `MED_CLINICAL_WRITER`, `INTAKE` schema, sequences, soft-delete and version columns, `RECORD_HISTORY`, `REQUEST_LOG`, `REFRESH_QUEUE` |
| 09, 10 | `PENDING_ITEM` and `PATIENT_CASE_SUMMARY` views |
| 20, 25 | transform raw clinical data, link medicines to drugs |
| 30, 31 | bulk build of the read models (as of `DEMO_AS_OF_DATE`, default today in IST) and embeddings |
| 35 | `REFRESH_PATIENT` (one patient; must equal the bulk build, proven by `tests/integration/test_refresh_patient.py`) and the refresh queue procedures |
| 36, 37 | write procedures (`REGISTER_PATIENT`, `WRITE_RECORD`) and report procedures |
| 40, 50 | Cortex Analyst semantic view, Cortex Search service (rebuild: drop it, then `db.py apply 50`) |
| 60, 90 | grants and the checks run by `db.py check` |

Order after a change to the clinical data: `apply 25`, then `apply 30`. Writes go only through the `MED_CLINICAL_WRITER` procedures (see ADR 25 in `docs/architecture/decisions.md`).
