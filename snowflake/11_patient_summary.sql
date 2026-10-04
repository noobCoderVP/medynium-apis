-- 11_patient_summary.sql: the stored written summary of a patient (agentic upgrade, phase I). Run as MED_ADMIN. Idempotent.
--
-- One row per patient, shared by everyone entitled to the patient (PATIENT_RAP): the summary is written once, shown on the
-- timeline and the overview, and rewritten only when a person presses Refresh. SIGNAL_HASH is a fingerprint of the facts it
-- was written from, so the screen can say "the record has changed since" without writing anything.
USE ROLE MED_ADMIN;
USE WAREHOUSE {{WH}};
USE SCHEMA {{DB}}.ANALYTICS;

CREATE TABLE IF NOT EXISTS PATIENT_SUMMARY (
  PATIENT_ID VARCHAR NOT NULL,
  SUMMARY_MD VARCHAR NOT NULL COMMENT 'Markdown, written from the record by a model and checked against it, or the rule-made fallback.',
  SOURCE VARCHAR NOT NULL COMMENT 'model or rules.',
  MODEL VARCHAR,
  SIGNAL_HASH VARCHAR NOT NULL COMMENT 'Fingerprint of the facts the summary was written from.',
  GENERATED_AT TIMESTAMP_NTZ NOT NULL,
  GENERATED_BY VARCHAR NOT NULL COMMENT 'User id of the person who pressed Refresh (or opened the patient first).',
  PRIMARY KEY (PATIENT_ID)
) COMMENT = 'The latest written summary per patient. Replaced, not appended. PATIENT_RAP.';

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE PATIENT_SUMMARY TO ROLE MED_DOCTOR;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE PATIENT_SUMMARY TO ROLE MED_ASSISTANT;

CALL SECURITY.APPLY_POLICIES();
