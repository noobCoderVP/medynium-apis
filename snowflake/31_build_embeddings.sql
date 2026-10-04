-- 31_build_embeddings.sql: embed every patient's case summary (production plan Phase 5). Run as MED_ADMIN after 30.
-- After this, INTAKE.REFRESH_EMBEDDING keeps one patient current after a change, and embeds only when the summary changed.
USE ROLE MED_ADMIN;
USE WAREHOUSE {{WH}};
USE SCHEMA {{DB}}.ANALYTICS;

TRUNCATE TABLE PATIENT_EMBEDDING;
INSERT INTO PATIENT_EMBEDDING
SELECT PATIENT_ID, SUMMARY_TEXT, SHA2(SUMMARY_TEXT, 256),
       SNOWFLAKE.CORTEX.EMBED_TEXT_1024('snowflake-arctic-embed-l-v2.0', SUMMARY_TEXT),
       'snowflake-arctic-embed-l-v2.0', SYSDATE()
FROM PATIENT_CASE_SUMMARY;
