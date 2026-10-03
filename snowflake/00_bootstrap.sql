-- 00_bootstrap.sql: run ONCE as ACCOUNTADMIN (python scripts/db.py bootstrap). Idempotent.
-- Creates only what needs account-level rights: roles, warehouse, resource monitor, service user.
-- Everything after this runs as MED_ADMIN. No runtime path uses ACCOUNTADMIN or MED_ADMIN.

USE ROLE ACCOUNTADMIN;

-- Roles ------------------------------------------------------------------------------------
CREATE ROLE IF NOT EXISTS MED_ADMIN COMMENT = 'Setup only. Creates objects and loads data. Never used by the API.';
CREATE ROLE IF NOT EXISTS MED_PROVISIONER COMMENT = 'Owns per-user roles and the provisioning procedures. Only CREATE ROLE, no MANAGE GRANTS.';
CREATE ROLE IF NOT EXISTS MED_API COMMENT = 'Service identity role for the API. No privilege on patient tables.';

GRANT CREATE ROLE ON ACCOUNT TO ROLE MED_PROVISIONER;

-- The person running setup gets the setup roles (scripts connect as MED_ADMIN).
GRANT ROLE MED_ADMIN TO USER {{ADMIN_USER}};
GRANT ROLE MED_PROVISIONER TO USER {{ADMIN_USER}};

-- Base roles are owned by the provisioner so it can grant them to the per-user roles (U_<id>).
USE ROLE MED_PROVISIONER;
CREATE ROLE IF NOT EXISTS MED_DOCTOR COMMENT = 'Base role inherited by every doctor role U_<id>.';
CREATE ROLE IF NOT EXISTS MED_ASSISTANT COMMENT = 'Base role inherited by every assistant role U_<id>.';
CREATE ROLE IF NOT EXISTS MED_AGENT_READ COMMENT = 'Read-only scoped role for CoCo skills and the golden run.';
USE ROLE ACCOUNTADMIN;

-- Warehouse and cost guardrails (NFR-02) -----------------------------------------------------
CREATE WAREHOUSE IF NOT EXISTS {{WH}}
  WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE
  COMMENT = 'Medynium. XSMALL, suspends after 60 s.';
ALTER WAREHOUSE {{WH}} SET WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 AUTO_RESUME = TRUE;

-- Quota is warehouse credits only; Cortex AI usage is billed separately, watch it in Snowsight.
CREATE RESOURCE MONITOR IF NOT EXISTS MEDYNIUM_MONITOR
  WITH CREDIT_QUOTA = 100 FREQUENCY = MONTHLY START_TIMESTAMP = IMMEDIATELY
  TRIGGERS ON 50 PERCENT DO NOTIFY
           ON 80 PERCENT DO SUSPEND
           ON 95 PERCENT DO SUSPEND_IMMEDIATE;
ALTER WAREHOUSE {{WH}} SET RESOURCE_MONITOR = MEDYNIUM_MONITOR;

GRANT USAGE, OPERATE, MONITOR ON WAREHOUSE {{WH}} TO ROLE MED_ADMIN;
GRANT USAGE ON WAREHOUSE {{WH}} TO ROLE MED_API;
GRANT USAGE ON WAREHOUSE {{WH}} TO ROLE MED_DOCTOR;
GRANT USAGE ON WAREHOUSE {{WH}} TO ROLE MED_ASSISTANT;
GRANT USAGE ON WAREHOUSE {{WH}} TO ROLE MED_AGENT_READ;
GRANT USAGE ON WAREHOUSE {{WH}} TO ROLE MED_PROVISIONER;

-- Database: MED_ADMIN owns it (it already exists from the first connection check) --------------
CREATE DATABASE IF NOT EXISTS {{DB}};
GRANT OWNERSHIP ON DATABASE {{DB}} TO ROLE MED_ADMIN COPY CURRENT GRANTS;
GRANT OWNERSHIP ON ALL SCHEMAS IN DATABASE {{DB}} TO ROLE MED_ADMIN COPY CURRENT GRANTS;

-- Cortex ---------------------------------------------------------------------------------------
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE MED_API;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE MED_DOCTOR;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE MED_ASSISTANT;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE MED_AGENT_READ;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE MED_ADMIN;

-- Service user: key-pair only, no password, no secondary roles ---------------------------------
CREATE USER IF NOT EXISTS MED_API_SVC
  TYPE = SERVICE DEFAULT_ROLE = MED_API DEFAULT_WAREHOUSE = {{WH}}
  COMMENT = 'Medynium API service identity (key pair). Assumes U_<id> roles per request.';
ALTER USER MED_API_SVC SET DEFAULT_ROLE = MED_API DEFAULT_WAREHOUSE = {{WH}} DEFAULT_SECONDARY_ROLES = ();
ALTER USER MED_API_SVC SET RSA_PUBLIC_KEY = '{{API_PUBLIC_KEY}}';
GRANT ROLE MED_API TO USER MED_API_SVC;
