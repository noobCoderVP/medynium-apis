# Data dictionary

Status: **Draft for review.** One place for every planned table with each field described. It consolidates [security.md](security.md), [clinical.md](clinical.md), [knowledge.md](knowledge.md) and [analytics.md](analytics.md); those remain the detailed sources. Types are as stated there; where a type was not stated it is marked _(proposed)_.

Conventions: upper snake case; `<ENTITY>_ID` primary keys; timestamps are `TIMESTAMP_NTZ` in UTC; money is `NUMBER(12,2)` in INR; Snowflake does not enforce foreign keys, so load scripts check them. Every table with `PATIENT_ID` carries the row access policy `SECURITY.PATIENT_RAP`.

## Contents

1. [Claims and utilisation](#1-claims-and-utilisation): where claims live and how they connect
2. [CLINICAL](#2-clinical): patient, provider, encounter, diagnosis, medication, lab, procedure, claim, note
3. [ANALYTICS read models](#3-analytics-read-models): Patient 360, timeline, utilisation, worklist
4. [ANALYTICS answers, audit and workspace](#4-analytics-answers-audit-and-workspace)
5. [KNOWLEDGE](#5-knowledge): drugs, documents, chunks
6. [SECURITY](#6-security): users, invites, sessions, entitlements, auth events
7. [RAW](#7-raw): untouched Synthea tables

---

## 1. Claims and utilisation

**Requirement:** FR-04 (P0). Counts of outpatient visits, hospitalisations and procedures, approved amounts, and a claim linked to its encounter. Totals must match a SQL ground-truth check. The BRD risk register says to use Synthea claim exports so claims link to encounters. Claims submission, adjudication and fraud detection are explicit non-goals.

| Table | Schema | Role in the claims story |
| --- | --- | --- |
| `RAW.CLAIMS`, `RAW.CLAIMS_TRANSACTIONS` | RAW | Untouched Synthea CSVs. `claims.csv` carries no amounts; `claims_transactions.csv` carries them. |
| `CLINICAL.CLAIM` | CLINICAL | One row per claim, with billed, approved and outstanding amounts rolled up from the transactions. |
| `CLINICAL.ENCOUNTER` | CLINICAL | Holds the claim's visit. `CLAIM.ENCOUNTER_ID` joins here (from Synthea `APPOINTMENTID`, which matched the encounter for 382 of 382 sample claims). |
| `CLINICAL.PROVIDER` | CLINICAL | Who billed. |
| `ANALYTICS.UTILIZATION` | ANALYTICS | One row per patient, trailing 12 months: visit, emergency, hospitalisation and procedure counts and money totals. |
| `ANALYTICS.PATIENT_TIMELINE` | ANALYTICS | Includes `CLAIM` events linked to their encounter. |

**API:** `GET /patients/{id}/claims` (claims and utilisation), `GET /patients/{id}/timeline` (claim events). **UI:** the Claims tab of the patient workspace.

Open item from the docs: the treatment of patient versus payer payments and the claim status mapping is decided in Slice 1 after inspecting the 300-patient export. `CLAIM` below is the target shape.

---

## 2. CLINICAL

Synthetic, India-localised patient data. Write access: `MED_ADMIN` during load only.

### 2.1 PATIENT

One row per synthetic patient.

| Field | Type | Description |
| --- | --- | --- |
| `PATIENT_ID` | VARCHAR PK | Readable id, `P-####`, generated deterministically at load. |
| `SOURCE_ID` | VARCHAR | Synthea patient UUID, kept for traceability. |
| `FULL_NAME` | VARCHAR | Generated Indian name that replaces Synthea's. Never logged. |
| `BIRTH_DATE` | DATE | Date of birth. |
| `DEATH_DATE` | DATE | Date of death, null if alive. |
| `SEX` | VARCHAR | `M` or `F`, mapped from Synthea `GENDER`. |
| `MARITAL_STATUS` | VARCHAR | From Synthea `MARITAL`. |
| `CITY`, `STATE`, `PIN_CODE` | VARCHAR | Generated Indian address parts. |
| `PHONE` | VARCHAR | Optional generated `+91` number. |
| `DISPLAY_AGE_AS_OF` | DATE | The `DEMO_AS_OF_DATE`, so displayed age is reproducible. |

Dropped on load: SSN, driver's licence, passport, prefix, suffix, maiden name, race, ethnicity, birthplace, county, FIPS, lat/lon, healthcare expenses, coverage and income.

### 2.2 PROVIDER

Not patient-keyed, so no policy.

| Field | Type | Description |
| --- | --- | --- |
| `PROVIDER_ID` | VARCHAR PK | `PRV-###`. |
| `NAME` | VARCHAR | Provider name, localised. |
| `SPECIALITY` | VARCHAR | Clinical speciality. |
| `ORGANIZATION_NAME` | VARCHAR | Hospital name from Synthea organisations, localised to an Indian hospital. |

### 2.3 ENCOUNTER

| Field | Type | Description |
| --- | --- | --- |
| `ENCOUNTER_ID` | VARCHAR PK | `ENC-#####`; Synthea id kept in `SOURCE_ID`. |
| `SOURCE_ID` | VARCHAR _(proposed)_ | Synthea encounter UUID. |
| `PATIENT_ID` | VARCHAR | Patient the visit belongs to. |
| `STARTED_AT`, `ENDED_AT` | TIMESTAMP_NTZ | Visit start and end, UTC. |
| `ENCOUNTER_CLASS` | VARCHAR | Synthea class: ambulatory, emergency, inpatient, outpatient, snf, urgentcare, virtual, wellness. |
| `CODE`, `DESCRIPTION` | VARCHAR | SNOMED code and text for the encounter. |
| `PROVIDER_ID` | VARCHAR | Provider who saw the patient. |
| `REASON_CODE`, `REASON_DESCRIPTION` | VARCHAR | Why the visit happened. |
| `BASE_COST_INR`, `TOTAL_CLAIM_COST_INR`, `PAYER_COVERAGE_INR` | NUMBER(12,2) | Encounter cost, total claimed and the part covered by the payer, converted from USD. |
| `VISIT_KIND` | VARCHAR | Derived: `OUTPATIENT` (ambulatory, outpatient, wellness, urgentcare, virtual), `EMERGENCY`, `HOSPITALIZATION` (inpatient, snf). Drives utilisation counts. |

### 2.4 DIAGNOSIS

From Synthea conditions.

| Field | Type | Description |
| --- | --- | --- |
| `DIAGNOSIS_ID` | VARCHAR PK | `DX-####`. |
| `PATIENT_ID`, `ENCOUNTER_ID` | VARCHAR | Patient and the encounter where it was recorded. |
| `CODE_SYSTEM`, `CODE`, `DESCRIPTION` | VARCHAR | Coding system (SNOMED), code and text. |
| `ONSET_DATE` | DATE | When the condition started. |
| `RESOLVED_DATE` | DATE | When it ended; null while active. |
| `IS_ACTIVE` | BOOLEAN | True when `RESOLVED_DATE` is null. |

### 2.5 MEDICATION

| Field | Type | Description |
| --- | --- | --- |
| `MEDICATION_ID` | VARCHAR PK | `RX-#####`. |
| `PATIENT_ID`, `ENCOUNTER_ID` | VARCHAR | Patient and prescribing encounter. |
| `RXNORM_CODE` | VARCHAR | RxNorm code from Synthea. |
| `DESCRIPTION` | VARCHAR | Original string, e.g. "24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet". |
| `DRUG_ID` | VARCHAR | Link to `KNOWLEDGE.DRUG` through `DRUG_NAME_MAP`. Null when the drug is not in the corpus (the gap case, S4). |
| `DRUG_NAME` | VARCHAR | Normalised generic name for display. |
| `STRENGTH_TEXT` | VARCHAR | Parsed strength such as `500 MG`; best effort. |
| `DOSE_TEXT` | VARCHAR | Human sentence such as "1000 mg twice daily"; seeded for demo patients, derived for generated ones. |
| `START_DATE`, `STOP_DATE` | DATE | Start and stop dates. |
| `IS_ACTIVE` | BOOLEAN | True when there is no stop date. |
| `LAST_CHANGE_DATE`, `CHANGE_NOTE` | DATE, VARCHAR | For seeded medication changes, e.g. a dose raised. |
| `DISPENSES` | NUMBER | Number of dispenses. |
| `TOTAL_COST_INR` | NUMBER(12,2) | Cost, optionally replaced by A-Z India price data. |
| `REASON_CODE`, `REASON_DESCRIPTION` | VARCHAR | Reason it was prescribed. |

### 2.6 LAB_RESULT

From Synthea observations (laboratory, plus selected vitals).

| Field | Type | Description |
| --- | --- | --- |
| `LAB_ID` | VARCHAR PK | `LAB-#####`. |
| `PATIENT_ID`, `ENCOUNTER_ID` | VARCHAR | Patient and encounter. |
| `OBSERVED_AT` | TIMESTAMP_NTZ | When the result was observed. |
| `LOINC_CODE`, `TEST_NAME` | VARCHAR | Test identity, e.g. `33914-3` eGFR, `38483-4` creatinine. |
| `VALUE_NUM` | NUMBER(18,4) | Numeric result, when the type is numeric. |
| `VALUE_TEXT` | VARCHAR | Text result, when the type is text. |
| `UNIT` | VARCHAR | Normalised unit, e.g. `mL/min/1.73 m²`. |
| `REF_LOW`, `REF_HIGH` | NUMBER | Reference range from `LAB_REFERENCE` (Synthea supplies none). |
| `ABNORMAL_FLAG` | VARCHAR | `LOW`, `HIGH`, `NORMAL`, or null when no range is known. |

### 2.7 LAB_REFERENCE

Not patient-keyed. Hand-maintained for the demo tests (eGFR, creatinine, HbA1c, potassium, sodium, haemoglobin, TSH, LDL).

| Field | Type | Description |
| --- | --- | --- |
| `LOINC_CODE` | VARCHAR PK _(proposed)_ | Test code. |
| `TEST_NAME` | VARCHAR | Test name. |
| `UNIT` | VARCHAR | Unit the range applies to. |
| `REF_LOW`, `REF_HIGH` | NUMBER | Normal range bounds. |
| `SOURCE_NOTE` | VARCHAR | Where the range came from. |

### 2.8 PROCEDURE

| Field | Type | Description |
| --- | --- | --- |
| `PROCEDURE_ID` | VARCHAR PK | `PRC-####`. |
| `PATIENT_ID`, `ENCOUNTER_ID` | VARCHAR | Patient and encounter. |
| `CODE_SYSTEM`, `CODE`, `DESCRIPTION` | VARCHAR | Coding system, code and text. |
| `PERFORMED_AT` | TIMESTAMP_NTZ _(proposed)_ | When it was performed. |
| `BASE_COST_INR` | NUMBER(12,2) | Procedure cost. |
| `REASON_CODE`, `REASON_DESCRIPTION` | VARCHAR | Why it was done. |

### 2.9 CLAIM

Built from Synthea `claims.csv` and `claims_transactions.csv`.

| Field | Type | Description |
| --- | --- | --- |
| `CLAIM_ID` | VARCHAR PK | `CLM-####`; Synthea id kept in `SOURCE_ID`. |
| `SOURCE_ID` | VARCHAR _(proposed)_ | Synthea claim UUID. |
| `PATIENT_ID` | VARCHAR | Patient the claim is for (Synthea `PATIENTID`). |
| `ENCOUNTER_ID` | VARCHAR | The encounter billed (Synthea `APPOINTMENTID`). This is the claim-to-encounter link. |
| `PROVIDER_ID` | VARCHAR | Billing provider. |
| `SERVICE_DATE` | DATE | Date of service. |
| `STATUS` | VARCHAR | Synthea `STATUS1` (`BILLED`, `CLOSED`, ...), mapped where possible to `SUBMITTED`, `APPROVED`, `PARTIAL`, `DENIED`. |
| `BILLED_INR` | NUMBER(12,2) | Sum of `CHARGE` transactions. |
| `APPROVED_INR` | NUMBER(12,2) | Sum of payer `PAYMENT` transactions. |
| `OUTSTANDING_INR` | NUMBER(12,2) | `OUTSTANDING1 + OUTSTANDING2 + OUTSTANDINGP`, converted. |
| `PRIMARY_DIAGNOSIS_CODE` | VARCHAR | Primary diagnosis on the claim (Synthea `DIAGNOSIS1`). |

### 2.10 CLINICAL_NOTE

About 20 script-generated notes plus the seeded ones.

| Field | Type | Description |
| --- | --- | --- |
| `NOTE_ID` | VARCHAR PK | e.g. `DOC-ED-20931`, `DOC-DS-19877`. |
| `PATIENT_ID`, `ENCOUNTER_ID` | VARCHAR | Patient and encounter. |
| `NOTE_TYPE` | VARCHAR | `ED_NOTE`, `DISCHARGE_SUMMARY` or `OUTPATIENT_NOTE`. |
| `TITLE`, `NOTE_DATE`, `AUTHOR` | VARCHAR, DATE, VARCHAR _(proposed)_ | Heading, date and author. |
| `BODY` | VARCHAR | Plain text. The S5 note contains an instruction aimed at AI tools, to test that it is ignored. |
| `CONTAINS_INJECTION` | BOOLEAN | Test marker only; never read by the agent. |

---

## 3. ANALYTICS read models

Precomputed at load with `CREATE OR REPLACE TABLE ... AS` (ADR-008), so page loads do no joins and no AI. "Recent" and change flags are relative to `DEMO_AS_OF_DATE` (default `2026-10-02`).

### 3.1 PATIENT_360

One row per patient; backs `GET /patients/{id}`.

| Field | Type | Description |
| --- | --- | --- |
| `PATIENT_ID` | VARCHAR PK | Patient. |
| `DISPLAY_ID`, `FULL_NAME`, `AGE_YEARS`, `SEX` | | Demographics copied from `CLINICAL.PATIENT`. |
| `ACTIVE_DIAGNOSES` | VARIANT | Array of `{diagnosis_id, description, onset_year, code}`. |
| `LAST_ENCOUNTER_ID`, `LAST_ENCOUNTER_DATE`, `LAST_ENCOUNTER_KIND` | | Most recent encounter on or before the as-of date. |
| `PREVIOUS_ENCOUNTER_DATE` | DATE | The visit before that; the "since last visit" baseline. |
| `ACTIVE_MEDICATION_COUNT` | NUMBER | Number of active medications. |
| `HAS_NEW_LAB` | BOOLEAN | A lab dated after the previous encounter exists. |
| `HAS_NEW_MEDICATION_CHANGE` | BOOLEAN | A medication started or changed since the baseline. |
| `HAS_RECENT_EMERGENCY` | BOOLEAN | Emergency visit in the 7 days before the as-of date. |
| `HAS_NEW_DOCUMENT` | BOOLEAN | A note newer than the baseline exists. |
| `SOURCE_TABLES` | VARIANT | Which tables each section came from, shown beside each value (FR-02). |

### 3.2 CURRENT_MEDICATIONS

Active medications per patient.

| Field | Type | Description |
| --- | --- | --- |
| `PATIENT_ID`, `MEDICATION_ID` | VARCHAR | Patient and medication. |
| `DRUG_NAME`, `DOSE_TEXT` | VARCHAR | Display name and dose sentence. |
| `START_DATE`, `LAST_CHANGE_DATE` | DATE | When started and last changed. |
| `CHANGE_NOTE` | VARCHAR | What changed. |
| `DRUG_ID`, `IN_CORPUS` | VARCHAR, BOOLEAN | Link to the knowledge base and whether a label is indexed. |

### 3.3 PATIENT_LAB_LATEST

Latest and previous result per patient and test.

| Field | Type | Description |
| --- | --- | --- |
| `PATIENT_ID`, `LOINC_CODE`, `TEST_NAME` | VARCHAR | Patient and test. |
| `LATEST_LAB_ID`, `LATEST_VALUE`, `LATEST_AT` | | The newest result. |
| `PREVIOUS_LAB_ID`, `PREVIOUS_VALUE`, `PREVIOUS_AT` | | The result before it. |
| `UNIT`, `REF_LOW`, `REF_HIGH`, `ABNORMAL_FLAG` | | Unit, reference range and flag. |
| `IS_NEW_SINCE_LAST_VISIT` | BOOLEAN | Newest result is after the last visit; feeds "what changed". |

### 3.4 PATIENT_TIMELINE

Merged, date-ordered events; backs `GET /patients/{id}/timeline`. Lab events are grouped into one `LAB_PANEL` per patient, date and encounter.

| Field | Type | Description |
| --- | --- | --- |
| `EVENT_ID` | VARCHAR PK | Event id. |
| `PATIENT_ID` | VARCHAR | Patient. |
| `EVENT_DATE` | DATE | Sort key, descending. |
| `EVENT_TYPE` | VARCHAR | `ENCOUNTER`, `DIAGNOSIS`, `MEDICATION_START`, `MEDICATION_CHANGE`, `LAB_PANEL`, `CLAIM`, `NOTE`. |
| `TITLE`, `SUMMARY` | VARCHAR | Display text. |
| `RECORD_ID`, `RECORD_TABLE` | VARCHAR | The underlying record, so selecting an event shows it (FR-03). |
| `ENCOUNTER_ID` | VARCHAR | Links a claim, lab or note to its encounter. |

### 3.5 UTILIZATION

One row per patient, trailing 12 months from the as-of date. Totals must match a SQL ground-truth query (FR-04).

| Field | Type | Description |
| --- | --- | --- |
| `PATIENT_ID` | VARCHAR PK _(proposed)_ | Patient. |
| `OPD_VISITS` | NUMBER | Outpatient visits. |
| `EMERGENCY_VISITS` | NUMBER | Emergency visits. |
| `HOSPITALIZATIONS` | NUMBER | Inpatient and skilled-nursing stays. |
| `PROCEDURES` | NUMBER | Procedures performed. |
| `BILLED_INR`, `APPROVED_INR`, `OUTSTANDING_INR` | NUMBER(12,2) | Claim totals for the period. |

### 3.6 DASHBOARD_WORKLIST

One row per patient. Because it carries the row access policy, each user's worklist is automatically their entitled patients.

| Field | Type | Description |
| --- | --- | --- |
| `PATIENT_ID` | VARCHAR PK _(proposed)_ | Patient. |
| Name, age, sex | | Identity for the list. |
| Main diagnoses | | Short list for the row. |
| Last encounter | | Date and kind. |
| Flag columns | BOOLEAN | `HAS_*` flags copied from `PATIENT_360`. |

---

## 4. ANALYTICS answers, audit and workspace

### 4.1 ANSWER

One row per stored answer; backs `GET /evidence/{answer_id}`. A user sees only their own answers (a second policy clause on `USER_ID`).

| Field | Type | Description |
| --- | --- | --- |
| `ANSWER_ID` | VARCHAR PK | `ANS-0001` style, unique across users. |
| `PATIENT_ID`, `USER_ID` | VARCHAR | Patient asked about and who asked. |
| `KIND` | VARCHAR | `SAFETY`, `CHANGED`, `MEDS`, `UTIL`, `KNOWLEDGE`. |
| `QUESTION` | VARCHAR | The question text. |
| `ROUTE`, `MODEL`, `CONFIDENCE` | | What the router chose. |
| `ANSWER_JSON` | VARIANT | The validated answer object. |
| `DROPPED_STATEMENTS` | VARIANT | What the validator removed, and why. |
| `CREATED_AT` | TIMESTAMP_NTZ | When it was created. |

### 4.2 ANSWER_EVIDENCE

| Field | Type | Description |
| --- | --- | --- |
| `ANSWER_ID` | VARCHAR | The answer. |
| `EVIDENCE_ID` | VARCHAR | Id scoped to the answer: `P1`, `P2`, `S1`. |
| `EVIDENCE_KIND` | VARCHAR | `PATIENT_RECORD`, `SQL`, `SOURCE_CHUNK`. |
| `PATIENT_ID` | VARCHAR | Set for patient records and SQL (policy applies). |
| `RECORD_TYPE`, `RECORD_ID`, `RECORD_TABLE`, `RECORD_DATE`, `VALUE_TEXT` | | For `PATIENT_RECORD`: which record and its value. |
| `SQL_TEXT`, `SQL_ROLE`, `ROW_COUNT`, `RAN_AT` | | For `SQL`: the query run, the role it ran under, rows returned, when. |
| `CHUNK_ID`, `DOCUMENT_ID` | VARCHAR | For `SOURCE_CHUNK`: the cited chunk and its document. |
| `SOURCE_SNAPSHOT` | VARIANT | Title, source, section, version, dates and text, so the answer replays even if the corpus is reloaded (NFR-05). |
| `MATCHED` | BOOLEAN | Whether the chunk supported a statement. |

### 4.3 COPILOT_AUDIT

Append-only; runtime roles insert only. A doctor reads their own rows; admins read all through a reporting view.

| Field | Type | Description |
| --- | --- | --- |
| `AUDIT_ID` | VARCHAR PK | Audit entry id. |
| `OCCURRED_AT` | TIMESTAMP_NTZ | When, UTC. |
| `USER_ID`, `ROLE_CODE` | VARCHAR | Who acted and their role. |
| `VIA` | VARCHAR | `USER` or `AGENT`. |
| `ACTION` | VARCHAR | `ASK`, `OPEN_PATIENT`, `SHOW_TIMELINE`, `RUN_SAFETY_REVIEW`, `PIN_EVIDENCE`, `DENIED_ACTION`, `DENIED_PATIENT`, and so on. |
| `ROUTE`, `MODEL`, `CONFIDENCE`, `COST_NOTE` | | Router decision; `COST_NOTE` such as "no model call". |
| `PATIENT_ID` | VARCHAR | Patient involved; may be set even when access was denied. |
| `QUESTION` | VARCHAR | The question text. |
| `ANSWER_ID` | VARCHAR | Resulting answer, if any. |
| `PATIENT_EVIDENCE_IDS`, `DOCUMENT_IDS` | VARIANT | Arrays of evidence used. |
| `STEPS` | VARIANT | The steps shown in the panel; identical to what was streamed (FR-21, AI-12). |
| `OUTCOME` | VARCHAR | `OK`, `DENIED`, `REFUSED`, `ERROR`, `ACTION_NOT_ALLOWED`. |
| `OUTCOME_DETAIL` | VARCHAR | Short reason, never a patient name. |

### 4.4 PIN

| Field | Type | Description |
| --- | --- | --- |
| `PIN_ID` | VARCHAR PK | Pin id. |
| `USER_ID`, `PATIENT_ID` | VARCHAR | Owner and patient. |
| `ANSWER_ID`, `EVIDENCE_ID` | VARCHAR | The pinned evidence. |
| `NOTE` | VARCHAR | Optional user note. |
| `CREATED_AT` | TIMESTAMP_NTZ | When pinned. |

### 4.5 SAVED_VIEW (P1)

Written only after the user approves a preview (FR-22).

| Field | Type | Description |
| --- | --- | --- |
| `VIEW_ID` | VARCHAR PK | View id. |
| `USER_ID`, `PATIENT_ID` | VARCHAR | Owner and patient. |
| `KIND` | VARCHAR | `SAVED_VIEW` or `VISIT_BRIEF`. |
| `TITLE` | VARCHAR | Display title. |
| `CONTENT` | VARIANT | The saved content. |
| `APPROVED_AT`, `CREATED_AT` | TIMESTAMP_NTZ | Approval and creation times. |

### 4.6 GOLDEN_RUN and GOLDEN_RESULT

Store the report from `POST /admin/golden-runs` (FR-11). The docs name the content but not exact columns, so the fields below are _(proposed)_.

| Table | Fields | Description |
| --- | --- | --- |
| `GOLDEN_RUN` | `RUN_ID`, `STARTED_AT`, `FINISHED_AT`, `PASS_RATE`, `ROUTING_ACCURACY` | One row per run with its headline scores. |
| `GOLDEN_RESULT` | `RUN_ID`, `QUESTION_ID`, `EXPECTED_ROUTE`, `ACTUAL_ROUTE`, `EXPECTED_CITATION`, `ACTUAL_CITATION`, `RESULT` | One row per question, including failures. |

`ANALYTICS.PATIENT_SEMANTIC_VIEW` is the Cortex Analyst semantic view over these tables; it is a view definition, not a table.

---

## 5. KNOWLEDGE

Public documents only. Never contains patient data (SEC-04), so no row access policy. Written at ingestion; never changed at run time.

### 5.1 DRUG

| Field | Type | Description |
| --- | --- | --- |
| `DRUG_ID` | VARCHAR PK | `DRG-###`. |
| `GENERIC_NAME` | VARCHAR | Lower-case ingredient name, e.g. `metformin`. |
| `DISPLAY_NAME` | VARCHAR | e.g. "Metformin hydrochloride". |
| `RXNORM_INGREDIENT` | VARCHAR | Ingredient RxCUI where known. |
| `IN_CORPUS` | BOOLEAN | True when a label is indexed. |
| `IN_NLEM` | BOOLEAN | On India's essential medicines list. |
| `NLEM_LEVEL` | VARCHAR | `P`, `S`, `T` or null (P1). |

### 5.2 DRUG_NAME_MAP

Links names in patient data and in India to a `DRUG`. Indian brands are included only when single-ingredient and in scope.

| Field | Type | Description |
| --- | --- | --- |
| `MAP_ID` | VARCHAR PK | Row id. |
| `DRUG_ID` | VARCHAR | The drug this name maps to. |
| `NAME_TEXT` | VARCHAR | The alias, lower-case, trimmed. |
| `NAME_KIND` | VARCHAR | `SYNTHEA_INGREDIENT`, `INDIAN_BRAND`, `ALTERNATE_GENERIC`. |
| `SOURCE` | VARCHAR | `SYNTHEA`, `AZ_INDIA`, `MANUAL`. |
| `COMPOSITION_TEXT` | VARCHAR | For Indian brands, e.g. `Metformin (500mg)`. |

### 5.3 DOCUMENT

One row per source document (one label version per drug).

| Field | Type | Description |
| --- | --- | --- |
| `DOCUMENT_ID` | VARCHAR PK | `DOC-MET-001` style. |
| `DRUG_ID` | VARCHAR | The drug; null for general guidelines. |
| `SOURCE` | VARCHAR | `openFDA`, `ICMR`, `NLEM`. |
| `DOC_TYPE` | VARCHAR | `DRUG_LABEL`, `GUIDELINE`, `ESSENTIAL_LIST`. |
| `TITLE` | VARCHAR | Document title. |
| `SOURCE_RECORD_ID` | VARCHAR | openFDA record id. |
| `VERSION_LABEL` | VARCHAR | Label version, shown as "Label version 6". |
| `EFFECTIVE_DATE` | DATE | Label effective date. |
| `RETRIEVED_AT`, `INGESTED_AT` | TIMESTAMP_NTZ | When fetched and when loaded. |
| `SOURCE_URL` | VARCHAR | Query URL or file path used. |
| `LICENSE_NOTE` | VARCHAR | Licence reminder. |
| `SOURCE_META` | VARIANT | `set_id`, brand and manufacturer names, `rxcui` list. |
| `CONTENT_HASH` | VARCHAR | SHA-256 of the raw text, so reruns are idempotent. |

### 5.4 DOCUMENT_CHUNK

The unit that is indexed and cited.

| Field | Type | Description |
| --- | --- | --- |
| `CHUNK_ID` | VARCHAR PK | `CH-####`. |
| `DOCUMENT_ID` | VARCHAR | Parent document. |
| `SECTION_KEY` | VARCHAR | openFDA field name, e.g. `contraindications`, `warnings_and_cautions`, `use_in_specific_populations`. |
| `SECTION_NAME` | VARCHAR | Heading shown to users. |
| `CHUNK_INDEX` | NUMBER | Order when a section is split. |
| `TEXT` | VARCHAR | Chunk text, 300 to 800 tokens, split on sentence boundaries. |
| `PAGE_NO` | NUMBER | Page, only for PDF guidelines. |
| `TOKEN_COUNT` | NUMBER | Size of the chunk. |
| `DRUG_ID`, `EFFECTIVE_DATE`, `VERSION_LABEL`, `SOURCE`, `TITLE` | | Denormalised for the search service and self-contained citations. |

### 5.5 SNAPSHOT

One row describing the corpus. The UI shows the snapshot date wherever evidence appears.

| Field | Type | Description |
| --- | --- | --- |
| `SNAPSHOT_DATE` | DATE | When the corpus was indexed. |
| `DOCUMENT_COUNT`, `CHUNK_COUNT`, `DRUG_COUNT` | NUMBER | Corpus size. |
| `NOTES` | VARCHAR | Free text. |

The Cortex Search service `KNOWLEDGE.LABEL_SEARCH` indexes `DOCUMENT_CHUNK.TEXT`.

---

## 6. SECURITY

Account, session and access data. No patient data.

### 6.1 APP_USER

| Field | Type | Description |
| --- | --- | --- |
| `USER_ID` | VARCHAR PK | UUID; builds the role name `U_<id without dashes>`. |
| `EMAIL` | VARCHAR | Unique, lower-case sign-in name. |
| `DISPLAY_NAME` | VARCHAR | e.g. "Dr. Sharma". |
| `ROLE_CODE` | VARCHAR | `DOCTOR` or `ASSISTANT`. |
| `IS_ADMIN` | BOOLEAN | Allows user and entitlement management; doctors only. |
| `SUPERVISING_DOCTOR_ID` | VARCHAR | Required for assistants; the doctor they work for. |
| `STATUS` | VARCHAR | `ACTIVE` or `DISABLED`. |
| `PASSWORD_HASH` | VARCHAR | argon2id string. Never logged or returned. |
| `PASSWORD_UPDATED_AT` | TIMESTAMP_NTZ | Last password change. |
| `FAILED_LOGINS` | NUMBER | Consecutive failures; reset on success. |
| `LOCKED_UNTIL` | TIMESTAMP_NTZ | Set for 15 minutes after 5 failures. |
| `TOKEN_VERSION` | NUMBER | Bumped on disable, password change or forced logout; carried in the access token. |
| `SNOWFLAKE_ROLE` | VARCHAR | `U_<id>`, created by `PROVISION_USER`. |
| `LAST_LOGIN_AT` | TIMESTAMP_NTZ | Last successful sign-in. |

### 6.2 USER_INVITE

| Field | Type | Description |
| --- | --- | --- |
| `INVITE_ID` | VARCHAR PK | UUID. |
| `EMAIL`, `DISPLAY_NAME` | VARCHAR | Invitee. |
| `ROLE_CODE`, `IS_ADMIN`, `SUPERVISING_DOCTOR_ID` | | Account to create on acceptance. |
| `PATIENT_IDS` | VARIANT | Patients to entitle on acceptance. |
| `TOKEN_HASH` | VARCHAR | SHA-256 of the one-time token; the token is never stored. |
| `STATUS` | VARCHAR | `PENDING`, `ACCEPTED`, `REVOKED`, `EXPIRED`. |
| `EXPIRES_AT` | TIMESTAMP_NTZ | 72 hours after creation. |

### 6.3 AUTH_SESSION

One row per refresh-token lineage (one sign-in on one device).

| Field | Type | Description |
| --- | --- | --- |
| `SESSION_ID` | VARCHAR PK | UUID; carried as `sid` in the access token. |
| `USER_ID` | VARCHAR | Owner. |
| `REFRESH_HASH` | VARCHAR | SHA-256 of the current refresh token. |
| `PREVIOUS_HASH` | VARCHAR | Hash of the previous token, kept to detect reuse. |
| `CREATED_AT`, `LAST_USED_AT`, `EXPIRES_AT` | TIMESTAMP_NTZ | Lifecycle; absolute lifetime is 7 days. |
| `REVOKED_AT` | TIMESTAMP_NTZ | Set on logout, reuse detection or disable. |
| `USER_AGENT`, `IP_ADDRESS` | VARCHAR | Activity trail only; never used for authorisation. |

### 6.4 PATIENT_ENTITLEMENT

Read by the row access policy.

| Field | Type | Description |
| --- | --- | --- |
| `ENTITLEMENT_ID` | VARCHAR PK | Row id. |
| `PATIENT_ID` | VARCHAR | Patient granted. |
| `USER_ID` | VARCHAR | User granted. |
| `SNOWFLAKE_ROLE` | VARCHAR | Copied from `APP_USER`; what the policy checks. |
| `GRANTED_BY`, `GRANTED_AT` | VARCHAR, TIMESTAMP_NTZ | Who granted and when. |
| `REVOKED_AT` | TIMESTAMP_NTZ | Null while active. |

Rules: an assistant is entitled only to patients their supervising doctor holds; revoking the doctor's entitlement revokes the assistants'; one active row per (patient, user).

### 6.5 AUTH_EVENT

Append-only.

| Field | Type | Description |
| --- | --- | --- |
| `EVENT_ID` | VARCHAR PK | Event id. |
| `EVENT_AT` | TIMESTAMP_NTZ | When, UTC. |
| `EVENT_TYPE` | VARCHAR | `LOGIN_SUCCESS`, `LOGIN_FAILURE`, `LOCKOUT`, `LOGOUT`, `REFRESH`, `REFRESH_REUSE`, `PASSWORD_CHANGE`, `INVITE_CREATED`, `INVITE_ACCEPTED`, `USER_DISABLED`, `USER_ENABLED`, `ENTITLEMENT_CHANGE`. |
| `USER_ID` | VARCHAR | Subject; null when the email is unknown. |
| `ACTOR_ID` | VARCHAR | The admin, when an admin acted. |
| `EMAIL_ATTEMPTED` | VARCHAR | For failed sign-ins. |
| `IP_ADDRESS`, `USER_AGENT` | VARCHAR | Request origin. |
| `DETAIL` | VARIANT | Structured extras, never secrets. |

Procedures: `PROVISION_USER`, `DEPROVISION_USER`, `SET_ENTITLEMENTS`. Policy: `SECURITY.PATIENT_RAP`.

---

## 7. RAW

Untouched copies of Synthea CSVs, one table per file, columns keep the CSV names and are all `VARCHAR`. Readable by setup roles only.

| Table | Feeds |
| --- | --- |
| `PATIENTS` | `CLINICAL.PATIENT` |
| `ENCOUNTERS` | `CLINICAL.ENCOUNTER` |
| `CONDITIONS` | `CLINICAL.DIAGNOSIS` |
| `MEDICATIONS` | `CLINICAL.MEDICATION` |
| `OBSERVATIONS` | `CLINICAL.LAB_RESULT` |
| `PROCEDURES` | `CLINICAL.PROCEDURE` |
| `CLAIMS` | `CLINICAL.CLAIM` (ids, dates, status, diagnosis) |
| `CLAIMS_TRANSACTIONS` | `CLINICAL.CLAIM` amounts; `TYPE` is `CHARGE`, `PAYMENT`, `TRANSFERIN` or `TRANSFEROUT` |
| `PROVIDERS`, `ORGANIZATIONS` | `CLINICAL.PROVIDER` |

Not loaded: allergies, care plans, devices, imaging, immunisations, payers, payer transitions, supplies.
