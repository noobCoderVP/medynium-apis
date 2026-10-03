# RAW and CLINICAL schemas

Synthetic patient data, localised for India. Column lists below were checked against a Synthea CSV export generated on this machine.

## RAW

Untouched copies of the Synthea CSV files, one table each, named after the file: `RAW.PATIENTS`, `ENCOUNTERS`, `CONDITIONS`, `MEDICATIONS`, `OBSERVATIONS`, `PROCEDURES`, `CLAIMS`, `CLAIMS_TRANSACTIONS`, `PROVIDERS`, `ORGANIZATIONS`. Columns keep the CSV names and are all `VARCHAR`. Only setup roles can read `RAW`. Files not loaded: allergies, careplans, devices, imaging, immunizations, payers, payer transitions, supplies (out of scope for the demo; can be added later).

## CLINICAL

All patient-keyed tables carry `PATIENT_ID` and the row access policy. Write access: `MED_ADMIN` during load only.

### PATIENT

| Column | Type | Source and notes |
| --- | --- | --- |
| `PATIENT_ID` | VARCHAR PK | `P-####`, generated. |
| `SOURCE_ID` | VARCHAR | Synthea `Id` (UUID). |
| `FULL_NAME` | VARCHAR | Generated Indian name, replaces Synthea's. |
| `BIRTH_DATE`, `DEATH_DATE` | DATE | `BIRTHDATE`, `DEATHDATE`. |
| `SEX` | VARCHAR | `GENDER` mapped to `M`, `F`. |
| `MARITAL_STATUS` | VARCHAR | `MARITAL`. |
| `CITY`, `STATE`, `PIN_CODE` | VARCHAR | Generated Indian address parts replace Synthea's. |
| `PHONE` | VARCHAR | Generated `+91` number, optional. |
| `DISPLAY_AGE_AS_OF` | DATE | The `DEMO_AS_OF_DATE`, so age is reproducible. |

Dropped: `SSN`, `DRIVERS`, `PASSPORT`, `PREFIX`, `SUFFIX`, `MAIDEN`, `RACE`, `ETHNICITY`, `BIRTHPLACE`, `COUNTY`, `FIPS`, `LAT`, `LON`, `HEALTHCARE_EXPENSES`, `HEALTHCARE_COVERAGE`, `INCOME`.

### PROVIDER

Not patient-keyed (no policy).

| Column | Type | Source |
| --- | --- | --- |
| `PROVIDER_ID` | VARCHAR PK | `PRV-###` |
| `NAME`, `SPECIALITY` | VARCHAR | `providers.csv` `NAME`, `SPECIALITY`; names localised |
| `ORGANIZATION_NAME` | VARCHAR | From `organizations.csv`, localised to an Indian hospital name |

### ENCOUNTER

| Column | Type | Source and notes |
| --- | --- | --- |
| `ENCOUNTER_ID` | VARCHAR PK | `ENC-#####`; Synthea `Id` in `SOURCE_ID`. |
| `PATIENT_ID` | VARCHAR | FK. |
| `STARTED_AT`, `ENDED_AT` | TIMESTAMP_NTZ | `START`, `STOP`, UTC. |
| `ENCOUNTER_CLASS` | VARCHAR | `ENCOUNTERCLASS`: `ambulatory`, `emergency`, `inpatient`, `outpatient`, `snf`, `urgentcare`, `virtual`, `wellness`. |
| `CODE`, `DESCRIPTION` | VARCHAR | SNOMED code and text. |
| `PROVIDER_ID` | VARCHAR | FK. |
| `REASON_CODE`, `REASON_DESCRIPTION` | VARCHAR | |
| `BASE_COST_INR`, `TOTAL_CLAIM_COST_INR`, `PAYER_COVERAGE_INR` | NUMBER(12,2) | Converted from USD. |
| `VISIT_KIND` | VARCHAR | Derived: `OUTPATIENT` (ambulatory, outpatient, wellness, urgentcare, virtual, home), `EMERGENCY`, `HOSPITALIZATION` (inpatient, snf, hospice). Drives utilisation counts. |

### DIAGNOSIS

From `conditions.csv`.

| Column | Type | Notes |
| --- | --- | --- |
| `DIAGNOSIS_ID` | VARCHAR PK | `DX-####` |
| `PATIENT_ID`, `ENCOUNTER_ID` | VARCHAR | FKs |
| `CODE_SYSTEM`, `CODE`, `DESCRIPTION` | VARCHAR | SNOMED |
| `ONSET_DATE` | DATE | `START` |
| `RESOLVED_DATE` | DATE | `STOP`; null while active |
| `IS_ACTIVE` | BOOLEAN | `RESOLVED_DATE IS NULL` |

### MEDICATION

From `medications.csv`. Synthea gives an RxNorm-style description string, such as `24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet`.

| Column | Type | Notes |
| --- | --- | --- |
| `MEDICATION_ID` | VARCHAR PK | `RX-#####` |
| `PATIENT_ID`, `ENCOUNTER_ID` | VARCHAR | FKs |
| `RXNORM_CODE` | VARCHAR | `CODE` |
| `DESCRIPTION` | VARCHAR | Original string. |
| `DRUG_ID` | VARCHAR | FK to `KNOWLEDGE.DRUG`, set by matching ingredient names through `DRUG_NAME_MAP`. Null when the drug is not in the corpus (the gap case, S4). |
| `DRUG_NAME` | VARCHAR | Normalised generic name for display. |
| `STRENGTH_TEXT` | VARCHAR | Parsed strength, e.g. `500 MG`. Best effort. |
| `DOSE_TEXT` | VARCHAR | Human sentence such as "1000 mg twice daily". Present for seeded patients; for generated ones derived from the description. |
| `START_DATE`, `STOP_DATE` | DATE | `START`, `STOP` |
| `IS_ACTIVE` | BOOLEAN | `STOP` is blank |
| `LAST_CHANGE_DATE`, `CHANGE_NOTE` | DATE, VARCHAR | For seeded medication changes (e.g. dose raised). |
| `DISPENSES` | NUMBER | |
| `TOTAL_COST_INR` | NUMBER(12,2) | Optionally replaced by A-Z India price data. |
| `REASON_CODE`, `REASON_DESCRIPTION` | VARCHAR | |

### LAB_RESULT

From `observations.csv`, `CATEGORY = laboratory` (and selected vital signs).

| Column | Type | Notes |
| --- | --- | --- |
| `LAB_ID` | VARCHAR PK | `LAB-#####` |
| `PATIENT_ID`, `ENCOUNTER_ID` | VARCHAR | FKs |
| `OBSERVED_AT` | TIMESTAMP_NTZ | `DATE` |
| `LOINC_CODE`, `TEST_NAME` | VARCHAR | e.g. `33914-3` eGFR, `38483-4` creatinine, `14959-1` microalbumin/creatinine |
| `VALUE_NUM` | NUMBER(18,4) | Present when `TYPE = numeric`. |
| `VALUE_TEXT` | VARCHAR | Present when `TYPE = text`. |
| `UNIT` | VARCHAR | `UNITS`, normalised (e.g. `mL/min/1.73 m²`). |
| `REF_LOW`, `REF_HIGH` | NUMBER | From `LAB_REFERENCE` (Synthea gives none). |
| `ABNORMAL_FLAG` | VARCHAR | `LOW`, `HIGH`, `NORMAL`, or null when no range is known. |

### LAB_REFERENCE

Not patient-keyed. Hand-maintained for the tests used in the demo (eGFR, creatinine, HbA1c, potassium, sodium, haemoglobin, TSH, LDL): `LOINC_CODE`, `TEST_NAME`, `UNIT`, `REF_LOW`, `REF_HIGH`, `SOURCE_NOTE`.

### PROCEDURE

From `procedures.csv`: `PROCEDURE_ID` (`PRC-####`), `PATIENT_ID`, `ENCOUNTER_ID`, `CODE_SYSTEM`, `CODE`, `DESCRIPTION`, `PERFORMED_AT`, `BASE_COST_INR`, `REASON_CODE`, `REASON_DESCRIPTION`.

### CLAIM

Built from `claims.csv` and `claims_transactions.csv`.

| Column | Type | Notes |
| --- | --- | --- |
| `CLAIM_ID` | VARCHAR PK | `CLM-####`; Synthea `Id` in `SOURCE_ID`. |
| `PATIENT_ID` | VARCHAR | `PATIENTID`. |
| `ENCOUNTER_ID` | VARCHAR | **`APPOINTMENTID`**, which equals the encounter `Id` for every claim in the sample (382 of 382). This is the claim-to-encounter link (FR-04). |
| `PROVIDER_ID` | VARCHAR | |
| `SERVICE_DATE` | DATE | `SERVICEDATE` |
| `STATUS` | VARCHAR | Derived, not copied (Synthea's status is always CLOSED): `SUBMITTED` (outstanding above zero), `SELF_PAY` (the payer paid nothing), `APPROVED` (the payer paid the whole charge), `PARTIAL` (the payer paid part and the patient the rest). |
| `BILLED_INR` | NUMBER(12,2) | Sum of `CHARGE` transactions. |
| `APPROVED_INR` | NUMBER(12,2) | Sum of payer `PAYMENT` transactions. |
| `OUTSTANDING_INR` | NUMBER(12,2) | `OUTSTANDING1 + OUTSTANDING2 + OUTSTANDINGP`, converted. |
| `PRIMARY_DIAGNOSIS_CODE` | VARCHAR | `DIAGNOSIS1` |

Built (Slice 1): Synthea's claim rows carry no amounts. They come from `claims_transactions`: billed is the sum of `CHARGE` rows (`AMOUNT`), paid is the sum of `PAYMENT` rows (`PAYMENTS`), approved is paid minus the patient's share (`TRANSFERIN`), outstanding is billed minus paid. **One encounter can have one to three claims** (382 claims over 283 encounters in the sample), so the relationship is one encounter to many claims.

### CLINICAL_NOTE

Generated by script (about 20), plus the seeded notes.

| Column | Type | Notes |
| --- | --- | --- |
| `NOTE_ID` | VARCHAR PK | `DOC-ED-20931`, `DOC-DS-19877`, etc. |
| `PATIENT_ID`, `ENCOUNTER_ID` | VARCHAR | FKs |
| `NOTE_TYPE` | VARCHAR | `ED_NOTE`, `DISCHARGE_SUMMARY`, `OUTPATIENT_NOTE` |
| `TITLE`, `NOTE_DATE`, `AUTHOR` | | |
| `BODY` | VARCHAR | Plain text. One seeded note (S5) contains an instruction aimed at AI tools. |
| `CONTAINS_INJECTION` | BOOLEAN | Test marker only; never read by the agent. |

## Integrity checks

Run after load; failures stop the pipeline.

1. Row counts match the CSVs (minus intentionally dropped rows).
2. Every `ENCOUNTER_ID` in child tables exists in `ENCOUNTER`.
3. Every `CLAIM.ENCOUNTER_ID` exists.
4. No `PATIENT_ID` in a child table missing from `PATIENT`.
5. No NULL `PATIENT_ID` in a patient-keyed table.
6. Dates are within plausible ranges and `ENDED_AT >= STARTED_AT`.
7. Seeded scenarios S1 to S5 have exactly the fields the demo needs ([data-loading.md](data-loading.md#seeded-scenarios)).
