# Database

Snowflake is the system of record. Source: SRS section 5 and implementation plan Slices 1 to 3. Column-level documentation is the next step and will live beside this file, one file per schema.

| Schema | Tables and views | Notes |
| --- | --- | --- |
| `RAW` | Synthea CSV loads | Untouched copies |
| `CLINICAL` | `PATIENT`, `ENCOUNTER`, `DIAGNOSIS`, `MEDICATION`, `LAB_RESULT`, `PROCEDURE`, `CLAIM`, `CLINICAL_NOTE` | `PATIENT_ID` on every table; encounter, procedure and claim IDs preserved so a claim joins to its encounter |
| `KNOWLEDGE` | `DOCUMENT`, `DOCUMENT_CHUNK`, `DRUG`, `DRUG_NAME_MAP`, `EVIDENCE` | Public documents only, never patient data (SEC-04) |
| `SECURITY` | `APP_USER`, `ROLE`, `PATIENT_ENTITLEMENT`, row access policies | Policy reads `PATIENT_ENTITLEMENT` for `CURRENT_USER()` |
| `ANALYTICS` | `PATIENT_360`, `PATIENT_TIMELINE`, `UTILIZATION`, `CURRENT_MEDICATIONS`, `DASHBOARD_WORKLIST`, `COPILOT_AUDIT`, `SAVED_VIEW` | Built at load time; policy attached to each; `COPILOT_AUDIT` is insert-only for runtime roles |

Roles: `MED_ADMIN` (setup only), `MED_DOCTOR`, `MED_ASSISTANT`, `MED_AGENT_READ`. Users: `SHARMA_DR`, `CLINIC_ASST`, `SECOND_DR`.

Seeded scenarios S1 to S5 are described in BRD section 9. Setup scripts go in [../../snowflake](../../snowflake), numbered in run order and idempotent.
