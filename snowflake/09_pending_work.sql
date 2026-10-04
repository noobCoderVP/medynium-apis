-- 09_pending_work.sql: "what is pending" as one view (production plan Phase 3). Run as MED_ADMIN. Idempotent.
--
-- A view, not a table: every source is already a read model or a findings row, so there is nothing to refresh and a
-- change shows the moment its source does. The row access policies on the sources apply to whoever queries the view,
-- so a user sees pending items only for patients they are entitled to.
--
-- Kinds, in the order they are shown (PRIORITY):
--   1 ESCALATED_FINDING  a finding escalated to someone who has the patient and not yet decided
--   2 FOLLOW_UP          a flagged finding with a follow-up date (the API marks it overdue against the as-of date)
--   3 OPEN_FINDING       a new finding nobody has decided on
--   4 REPORT_TO_REVIEW   an uploaded report whose extracted rows wait for a doctor
--   5 ABNORMAL_LAB       a result outside its range, new since the last visit, not yet marked reviewed
--   6 RECENT_EMERGENCY   an emergency visit in the last 7 days
USE ROLE MED_ADMIN;
USE WAREHOUSE {{WH}};
USE SCHEMA {{DB}}.ANALYTICS;

CREATE OR REPLACE VIEW PENDING_ITEM AS
SELECT 'F-' || f.FINDING_ID AS ITEM_ID, f.PATIENT_ID, p.FULL_NAME AS PATIENT_NAME,
       IFF(f.STATUS = 'ESCALATED', 'ESCALATED_FINDING', IFF(f.STATUS = 'FLAGGED', 'FOLLOW_UP', 'OPEN_FINDING')) AS KIND,
       IFF(f.STATUS = 'ESCALATED', 1, IFF(f.STATUS = 'FLAGGED', 2, 3)) AS PRIORITY,
       LEFT(f.SUMMARY, 200) AS TITLE,
       CASE f.STATUS WHEN 'ESCALATED' THEN 'Escalated for a decision' WHEN 'FLAGGED' THEN 'Flagged for follow-up'
                     ELSE 'Raised from a safety review' END AS DETAIL,
       f.FOLLOW_UP_ON AS DUE_DATE, f.CREATED_AT AS RAISED_AT,
       'ANALYTICS.FINDING' AS SOURCE_TABLE, f.FINDING_ID AS SOURCE_ID
FROM ANALYTICS.FINDING f JOIN ANALYTICS.PATIENT_360 p ON p.PATIENT_ID = f.PATIENT_ID
WHERE f.STATUS IN ('NEW', 'FLAGGED', 'ESCALATED')
UNION ALL
SELECT 'R-' || r.REPORT_ID, r.PATIENT_ID, p.FULL_NAME, 'REPORT_TO_REVIEW', 4,
       'Report waiting for review: ' || LEFT(r.FILENAME, 120),
       COALESCE(r.ROWS_KEPT, 0) || IFF(COALESCE(r.ROWS_KEPT, 0) = 1, ' item', ' items') || ' read from it'
         || IFF(r.IDENTITY_STATUS = 'MISMATCH', '; the name on it does not match this patient', ''),
       NULL, r.EXTRACTED_AT, 'CLINICAL.REPORT', r.REPORT_ID
FROM CLINICAL.REPORT r JOIN ANALYTICS.PATIENT_360 p ON p.PATIENT_ID = r.PATIENT_ID
WHERE r.STATUS = 'EXTRACTED'
UNION ALL
SELECT 'L-' || l.LATEST_LAB_ID, l.PATIENT_ID, p.FULL_NAME, 'ABNORMAL_LAB', 5,
       l.SHORT_NAME || ' ' || TO_VARCHAR(l.LATEST_VALUE, 'FM999990.0099') || COALESCE(' ' || l.UNIT, '')
         || ' (' || LOWER(l.ABNORMAL_FLAG) || ')',
       'Outside its reference range, new since the last visit', NULL, l.LATEST_AT,
       'CLINICAL.LAB_RESULT', l.LATEST_LAB_ID
FROM ANALYTICS.PATIENT_LAB_LATEST l JOIN ANALYTICS.PATIENT_360 p ON p.PATIENT_ID = l.PATIENT_ID
WHERE l.ABNORMAL_FLAG IN ('LOW', 'HIGH') AND l.IS_NEW_SINCE_LAST_VISIT
  AND NOT EXISTS (SELECT 1 FROM ANALYTICS.LAB_REVIEW r WHERE r.LAB_ID = l.LATEST_LAB_ID)
UNION ALL
SELECT 'E-' || p.LAST_ENCOUNTER_ID, p.PATIENT_ID, p.FULL_NAME, 'RECENT_EMERGENCY', 6,
       'Emergency visit on ' || TO_VARCHAR(p.LAST_ENCOUNTER_DATE, 'DD Mon YYYY'),
       COALESCE(p.LAST_ENCOUNTER_LABEL, 'Emergency visit'), NULL, p.LAST_ENCOUNTER_DATE::TIMESTAMP_NTZ,
       'CLINICAL.ENCOUNTER', p.LAST_ENCOUNTER_ID
FROM ANALYTICS.PATIENT_360 p
WHERE p.HAS_RECENT_EMERGENCY AND p.LAST_ENCOUNTER_KIND = 'EMERGENCY';

GRANT SELECT ON VIEW PENDING_ITEM TO ROLE MED_DOCTOR;
GRANT SELECT ON VIEW PENDING_ITEM TO ROLE MED_ASSISTANT;
GRANT SELECT ON VIEW PENDING_ITEM TO ROLE MED_AGENT_READ;
GRANT INSERT ON TABLE LAB_REVIEW TO ROLE MED_DOCTOR;
