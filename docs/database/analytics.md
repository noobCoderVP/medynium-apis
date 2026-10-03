# ANALYTICS schema

Precomputed tables for fast screens, plus the stores for answers, evidence, audit, pins and saved views. Derived tables are built at load time by `CREATE OR REPLACE TABLE ... AS` (ADR-008), so page loads do no joins and no AI. Every table here with `PATIENT_ID` carries the row access policy.

Build parameter: `DEMO_AS_OF_DATE` (default `2026-10-02`). "Last visit", "recent" and change flags are relative to it.

## Precomputed tables

### PATIENT_360

One row per patient. Backs `GET /patients/{id}`.

| Column | Type | Notes |
| --- | --- | --- |
| `PATIENT_ID` | VARCHAR PK | |
| `DISPLAY_ID`, `FULL_NAME`, `AGE_YEARS`, `SEX` | | From `CLINICAL.PATIENT` |
| `ACTIVE_DIAGNOSES` | VARIANT | Array of `{diagnosis_id, description, onset_year, code}` |
| `LAST_ENCOUNTER_ID`, `LAST_ENCOUNTER_DATE`, `LAST_ENCOUNTER_KIND` | | Most recent encounter on or before the as-of date |
| `PREVIOUS_ENCOUNTER_DATE` | DATE | The one before it; the "since last visit" baseline |
| `ACTIVE_MEDICATION_COUNT` | NUMBER | |
| `HAS_NEW_LAB` | BOOLEAN | Lab dated after `PREVIOUS_ENCOUNTER_DATE` |
| `HAS_NEW_MEDICATION_CHANGE` | BOOLEAN | |
| `HAS_RECENT_EMERGENCY` | BOOLEAN | Emergency in the 7 days before as-of |
| `HAS_NEW_DOCUMENT` | BOOLEAN | |
| `SOURCE_TABLES` | VARIANT | Which tables each section came from, shown with each value (FR-02) |

### CURRENT_MEDICATIONS

Active medications per patient (`IS_ACTIVE`), with `MEDICATION_ID`, `DRUG_NAME`, `DOSE_TEXT`, `START_DATE`, `LAST_CHANGE_DATE`, `CHANGE_NOTE`, `DRUG_ID`, `IN_CORPUS`.

### PATIENT_LAB_LATEST

For each patient and test: the latest and previous result, for the overview, the dashboard changes widget and "what changed". Columns: `PATIENT_ID`, `LOINC_CODE`, `TEST_NAME`, `LATEST_LAB_ID`, `LATEST_VALUE`, `LATEST_AT`, `PREVIOUS_LAB_ID`, `PREVIOUS_VALUE`, `PREVIOUS_AT`, `UNIT`, `REF_LOW`, `REF_HIGH`, `ABNORMAL_FLAG`, `IS_NEW_SINCE_LAST_VISIT`.

### PATIENT_TIMELINE

Merged, date-ordered events. Backs `GET /patients/{id}/timeline`.

| Column | Type | Notes |
| --- | --- | --- |
| `EVENT_ID` | VARCHAR PK | |
| `PATIENT_ID` | VARCHAR | |
| `EVENT_DATE` | DATE | Sort key, descending |
| `EVENT_TYPE` | VARCHAR | `ENCOUNTER`, `DIAGNOSIS`, `MEDICATION_START`, `MEDICATION_CHANGE`, `LAB_PANEL`, `CLAIM`, `NOTE` |
| `TITLE`, `SUMMARY` | VARCHAR | Display text |
| `RECORD_ID`, `RECORD_TABLE` | VARCHAR | Selecting an event shows the underlying record (FR-03) |
| `ENCOUNTER_ID` | VARCHAR | Links a claim, lab or note to its encounter |

Lab events are grouped into one `LAB_PANEL` per patient, date and encounter.

### UTILIZATION

One row per patient, trailing 12 months from the as-of date: `OPD_VISITS`, `EMERGENCY_VISITS`, `HOSPITALIZATIONS`, `PROCEDURES`, `BILLED_INR`, `APPROVED_INR`, `OUTSTANDING_INR`. Totals must match a SQL ground-truth query (FR-04).

### DASHBOARD_WORKLIST

One row per patient with the fields the worklist needs: name, age, sex, main diagnoses (short list), last encounter, and flag columns copied from `PATIENT_360`. Because the table carries the row access policy, each user's worklist is automatically their entitled patients. The dashboard totals are aggregates over what the policy lets that user see.

## Answers and evidence

### ANSWER

One row per stored answer. Backs `GET /evidence/{answer_id}` and the activity log.

| Column | Type | Notes |
| --- | --- | --- |
| `ANSWER_ID` | VARCHAR PK | `ANS-0001` style, unique across users (a sequence plus the user) |
| `PATIENT_ID` | VARCHAR | |
| `USER_ID` | VARCHAR | Who asked |
| `KIND` | VARCHAR | `SAFETY`, `CHANGED`, `MEDS`, `UTIL`, `KNOWLEDGE` |
| `QUESTION` | VARCHAR | |
| `ROUTE`, `MODEL`, `CONFIDENCE` | | From the router |
| `ANSWER_JSON` | VARIANT | The validated answer object ([ai-layer.md](../architecture/ai-layer.md#4-answer-object)) |
| `DROPPED_STATEMENTS` | VARIANT | What the validator removed, and why |
| `CREATED_AT` | TIMESTAMP_NTZ | |

A user sees only their own answers (a second policy clause on `USER_ID` in addition to the patient policy).

### ANSWER_EVIDENCE

| Column | Type | Notes |
| --- | --- | --- |
| `ANSWER_ID` | VARCHAR | FK |
| `EVIDENCE_ID` | VARCHAR | Scoped to the answer: `P1`, `P2`, `S1` |
| `EVIDENCE_KIND` | VARCHAR | `PATIENT_RECORD`, `SQL`, `SOURCE_CHUNK` |
| `PATIENT_ID` | VARCHAR | Present for patient records and SQL (policy applies) |
| `RECORD_TYPE`, `RECORD_ID`, `RECORD_TABLE`, `RECORD_DATE`, `VALUE_TEXT` | | For `PATIENT_RECORD` |
| `SQL_TEXT`, `SQL_ROLE`, `ROW_COUNT`, `RAN_AT` | | For `SQL` |
| `CHUNK_ID`, `DOCUMENT_ID` | | For `SOURCE_CHUNK`; the citation fields are read from `KNOWLEDGE` at display time and also snapshotted in `SOURCE_SNAPSHOT` |
| `SOURCE_SNAPSHOT` | VARIANT | Title, source, section, version, effective and retrieval dates, text, so the answer can be replayed even if the corpus is reloaded (NFR-05) |
| `MATCHED` | BOOLEAN | Whether the chunk supported a statement |

## Audit

### COPILOT_AUDIT

Append-only. One row per Copilot question, agent action or denied attempt. Runtime roles insert only.

| Column | Type | Notes |
| --- | --- | --- |
| `AUDIT_ID` | VARCHAR PK | |
| `OCCURRED_AT` | TIMESTAMP_NTZ | UTC |
| `USER_ID`, `ROLE_CODE` | VARCHAR | |
| `VIA` | VARCHAR | `USER`, `AGENT` |
| `ACTION` | VARCHAR | `ASK`, `OPEN_PATIENT`, `SHOW_TIMELINE`, `RUN_SAFETY_REVIEW`, `PIN_EVIDENCE`, `DENIED_ACTION`, `DENIED_PATIENT`, `SIGN_IN`, and so on |
| `ROUTE`, `MODEL`, `CONFIDENCE`, `COST_NOTE` | | From the router; `COST_NOTE` such as "no model call" |
| `PATIENT_ID` | VARCHAR | May be set even when access was denied; the policy still restricts who can read this row |
| `QUESTION` | VARCHAR | |
| `ANSWER_ID` | VARCHAR | |
| `PATIENT_EVIDENCE_IDS`, `DOCUMENT_IDS` | VARIANT | Arrays |
| `STEPS` | VARIANT | The steps shown in the panel; equals the audit entry for the same run (FR-21, AI-12) |
| `OUTCOME` | VARCHAR | `OK`, `DENIED`, `REFUSED`, `ERROR`, `ACTION_NOT_ALLOWED` |
| `OUTCOME_DETAIL` | VARCHAR | Short reason, never a patient name |

A doctor reads their own rows; admins read all rows through a separate reporting view.

## Workspace state

### PIN

`PIN_ID`, `USER_ID`, `PATIENT_ID`, `ANSWER_ID`, `EVIDENCE_ID`, `NOTE`, `CREATED_AT`. Created by the `pin_evidence` action or the pin icon. A user reads only their own pins.

### FINDING
A clinician's decision on a safety-review statement: `STATUS` (NEW, ACKNOWLEDGED, FLAGGED, DISMISSED, ESCALATED), `REASON` (required to dismiss), `FOLLOW_UP_ON` (required to flag), `ASSIGNED_TO` (a colleague who has the patient, required to escalate), plus who raised and last changed it and when. Shared by everyone entitled to the patient, so it carries `PATIENT_RAP`, not the own-rows policy. `MED_DOCTOR` and `MED_ASSISTANT` can insert and update it; only the API's findings feature does. Create with `db.py apply 05`, `06`, `60`.

### SAVED_VIEW (P1)

`VIEW_ID`, `USER_ID`, `PATIENT_ID`, `KIND` (`SAVED_VIEW`, `VISIT_BRIEF`), `TITLE`, `CONTENT` (VARIANT), `APPROVED_AT`, `CREATED_AT`. Written only after the user approves a preview (FR-22). The agent role has no write privilege on any `CLINICAL` table.

### GOLDEN_RUN, GOLDEN_RESULT

Store the report from `POST /admin/golden-runs`: run id, started and finished times, pass rate, routing accuracy; per question the expected and actual citation, route and result, including failures (FR-11).

## Semantic view

`ANALYTICS.PATIENT_SEMANTIC_VIEW` is defined over the protected `ANALYTICS` and `CLINICAL` tables with synonyms and verified queries (Slice 5). It is a view definition, not a table, and inherits the row access policy through its sources.

## As built

- Read models rebuilt by `snowflake/30_build_analytics.sql` with `TRUNCATE` and `INSERT`, so comments and policy attachments persist. Worklist: 307 patients (300 generated, 7 seeded).
- Change flags compare to the previous visit: `HAS_NEW_LAB` (a reference-range test newer than the previous visit), `HAS_NEW_MEDICATION_CHANGE` (a start or change after it), `HAS_RECENT_EMERGENCY` (an ED visit in the 7 days before the as-of date), `HAS_NEW_DOCUMENT` (a note newer than the **last** visit).
- `ANSWER_EVIDENCE` gained `USER_ID`; answer kinds are `SAFETY`, `CHANGED`, `MEDS`, `LABS`, `UTIL`, `SUMMARY`, `ANALYST`, `KNOWLEDGE`. `PIN` carries an `IDEMPOTENCY_KEY`.
- The semantic view `PATIENT_SEMANTIC_VIEW` exists over the read models (verified queries not added).
