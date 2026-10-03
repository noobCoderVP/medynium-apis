-- 40_semantic_view.sql: the Cortex Analyst semantic view over the precomputed read models (D-11).
-- It reads row-access-policy tables, so Analyst-generated SQL run under a user's role only ever sees that user's
-- entitled patients. The API additionally requires the generated SQL to name the one patient in scope.
USE ROLE MED_ADMIN;
USE WAREHOUSE {{WH}};
USE SCHEMA {{DB}}.ANALYTICS;

CREATE OR REPLACE SEMANTIC VIEW PATIENT_SEMANTIC_VIEW
  TABLES (
    patients AS ANALYTICS.PATIENT_360 PRIMARY KEY (PATIENT_ID)
      COMMENT = 'One row per patient: demographics, last and previous visit, and change flags',
    meds AS ANALYTICS.CURRENT_MEDICATIONS PRIMARY KEY (MEDICATION_ID)
      COMMENT = 'Active medications for each patient',
    labs AS ANALYTICS.PATIENT_LAB_LATEST PRIMARY KEY (PATIENT_ID, LOINC_CODE)
      COMMENT = 'Latest and previous result for each patient and laboratory test',
    timeline AS ANALYTICS.PATIENT_TIMELINE PRIMARY KEY (EVENT_ID)
      COMMENT = 'Dated events: visits, diagnoses, medication starts and changes, lab panels, claims, notes',
    util AS ANALYTICS.UTILIZATION PRIMARY KEY (PATIENT_ID)
      COMMENT = 'Visits, hospital stays, procedures and amounts for the last 12 months'
  )
  RELATIONSHIPS (
    meds_to_patients AS meds (PATIENT_ID) REFERENCES patients,
    labs_to_patients AS labs (PATIENT_ID) REFERENCES patients,
    timeline_to_patients AS timeline (PATIENT_ID) REFERENCES patients,
    util_to_patients AS util (PATIENT_ID) REFERENCES patients
  )
  DIMENSIONS (
    patients.patient_id AS PATIENT_ID WITH SYNONYMS = ('patient', 'patient id', 'mrn'),
    patients.patient_name AS FULL_NAME WITH SYNONYMS = ('name', 'patient name'),
    patients.age AS AGE_YEARS,
    patients.sex AS SEX,
    patients.last_visit_date AS LAST_ENCOUNTER_DATE WITH SYNONYMS = ('last visit', 'most recent visit'),
    patients.previous_visit_date AS PREVIOUS_ENCOUNTER_DATE WITH SYNONYMS = ('previous visit', 'visit before the last', 'prior visit'),
    meds.medication_name AS DRUG_NAME WITH SYNONYMS = ('medicine', 'drug', 'medication', 'tablet'),
    meds.dose AS DOSE_TEXT WITH SYNONYMS = ('dose', 'dosage', 'strength'),
    meds.medication_start AS START_DATE WITH SYNONYMS = ('started', 'start date'),
    meds.medication_change_note AS CHANGE_NOTE WITH SYNONYMS = ('dose change', 'what changed'),
    labs.test_name AS SHORT_NAME WITH SYNONYMS = ('lab', 'test', 'laboratory test', 'investigation'),
    labs.latest_at AS LATEST_AT WITH SYNONYMS = ('latest date', 'most recent result date'),
    labs.abnormal_flag AS ABNORMAL_FLAG WITH SYNONYMS = ('abnormal', 'out of range', 'low or high'),
    timeline.event_date AS EVENT_DATE WITH SYNONYMS = ('date', 'when'),
    timeline.event_type AS EVENT_TYPE WITH SYNONYMS = ('type of event', 'kind of event'),
    timeline.event_title AS TITLE,
    timeline.event_summary AS SUMMARY WITH SYNONYMS = ('details', 'description')
  )
  METRICS (
    labs.latest_result AS AVG(labs.LATEST_VALUE) WITH SYNONYMS = ('latest value', 'current value', 'egfr', 'kidney function', 'sugar', 'hba1c', 'potassium'),
    labs.previous_result AS AVG(labs.PREVIOUS_VALUE) WITH SYNONYMS = ('previous value', 'earlier value'),
    util.outpatient_visits AS SUM(util.OPD_VISITS) WITH SYNONYMS = ('opd visits', 'clinic visits', 'outpatient visits'),
    util.emergency_visits AS SUM(util.EMERGENCY_VISITS) WITH SYNONYMS = ('er visits', 'ed visits', 'emergency visits'),
    util.hospital_stays AS SUM(util.HOSPITALIZATIONS) WITH SYNONYMS = ('admissions', 'hospitalizations', 'inpatient stays'),
    util.procedure_count AS SUM(util.PROCEDURES) WITH SYNONYMS = ('procedures'),
    util.approved_amount AS SUM(util.APPROVED_INR) WITH SYNONYMS = ('approved', 'paid', 'insurance approved', 'cost')
  )
  COMMENT = 'Medynium patient facts for Cortex Analyst. Always scoped to one patient by the caller.';

GRANT SELECT ON SEMANTIC VIEW PATIENT_SEMANTIC_VIEW TO ROLE MED_DOCTOR;
GRANT SELECT ON SEMANTIC VIEW PATIENT_SEMANTIC_VIEW TO ROLE MED_ASSISTANT;
GRANT SELECT ON SEMANTIC VIEW PATIENT_SEMANTIC_VIEW TO ROLE MED_AGENT_READ;
