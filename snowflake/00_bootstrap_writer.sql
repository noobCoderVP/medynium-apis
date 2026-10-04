-- 00_bootstrap_writer.sql: the one privilege MED_ADMIN cannot grant itself. Run once as ACCOUNTADMIN:
--   python scripts/db.py bootstrap-writer
-- The INTAKE procedures run as MED_CLINICAL_WRITER (08_write_path.sql) and embed a patient's case summary after a change.
USE ROLE ACCOUNTADMIN;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE MED_CLINICAL_WRITER;
