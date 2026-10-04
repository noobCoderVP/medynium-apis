-- 10_similar_patients.sql: the text a patient is embedded from (production plan Phase 5). Run as MED_ADMIN.
--
-- One view is the single source of the summary, used by the bulk build (31) and by the per-patient refresh (35). It is
-- built only from read models and holds nothing that identifies a person: no name, city, id or note text. Free text from
-- notes is never in it, so text planted in a note can never reach an embedding or a model.
USE ROLE MED_ADMIN;
USE WAREHOUSE {{WH}};
USE SCHEMA {{DB}}.ANALYTICS;

CREATE OR REPLACE VIEW PATIENT_CASE_SUMMARY AS
SELECT p.PATIENT_ID,
       'Sex ' || p.SEX || ', age ' || (FLOOR(p.AGE_YEARS / 5) * 5) || ' to ' || (FLOOR(p.AGE_YEARS / 5) * 5 + 4) || '. '
       || 'Active diagnoses: ' || COALESCE(dx.TXT, 'none recorded') || '. '
       || 'Current medicines: ' || COALESCE(rx.TXT, 'none recorded') || '. '
       || 'Latest abnormal results: ' || COALESCE(lab.TXT, 'none') || '.'
       || IFF(p.HAS_RECENT_EMERGENCY, ' Recent emergency visit.', '') AS SUMMARY_TEXT
FROM PATIENT_360 p
LEFT JOIN (
  SELECT x.PATIENT_ID, LISTAGG(DISTINCT d.VALUE:description::VARCHAR, '; ') WITHIN GROUP (ORDER BY d.VALUE:description::VARCHAR) AS TXT
  FROM PATIENT_360 x, LATERAL FLATTEN(INPUT => x.ACTIVE_DIAGNOSES) d GROUP BY x.PATIENT_ID
) dx ON dx.PATIENT_ID = p.PATIENT_ID
LEFT JOIN (
  SELECT PATIENT_ID, LISTAGG(DISTINCT COALESCE(DRUG_NAME, DESCRIPTION), ', ') WITHIN GROUP (ORDER BY COALESCE(DRUG_NAME, DESCRIPTION)) AS TXT
  FROM CURRENT_MEDICATIONS GROUP BY PATIENT_ID
) rx ON rx.PATIENT_ID = p.PATIENT_ID
LEFT JOIN (
  SELECT PATIENT_ID, LISTAGG(SHORT_NAME || ' ' || LOWER(ABNORMAL_FLAG), ', ') WITHIN GROUP (ORDER BY SHORT_NAME) AS TXT
  FROM PATIENT_LAB_LATEST WHERE ABNORMAL_FLAG IN ('LOW', 'HIGH') GROUP BY PATIENT_ID
) lab ON lab.PATIENT_ID = p.PATIENT_ID;

-- The INTAKE procedures run as MED_CLINICAL_WRITER and keep one patient's vector current.
GRANT SELECT ON VIEW PATIENT_CASE_SUMMARY TO ROLE MED_CLINICAL_WRITER;
GRANT SELECT, INSERT, DELETE ON TABLE PATIENT_EMBEDDING TO ROLE MED_CLINICAL_WRITER;
