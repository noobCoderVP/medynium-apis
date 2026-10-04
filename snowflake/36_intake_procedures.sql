-- 36_intake_procedures.sql: the write procedures (production plan, P1.3 to P1.5). Created and owned by
-- MED_CLINICAL_WRITER; called by the API's service role (MED_API) with the verified actor's user id.
--
-- Every write: (1) the actor must be an active doctor, (2) the actor must hold an unrevoked entitlement to the patient,
-- (3) an Idempotency-Key replays the first result, (4) an edit must carry the row's current VERSION or it is a conflict,
-- (5) the change and its before and after images go to CLINICAL.RECORD_HISTORY, (6) a refresh of the patient's read
-- models is queued for the API's worker (registering a patient refreshes at once). Results are {ok, ...} objects; errors are {ok: false, error: <code>} where the code is one of
-- forbidden, denied, not_found, conflict, invalid. The API turns denied and not_found into the same 404.
USE ROLE MED_CLINICAL_WRITER;
USE WAREHOUSE {{WH}};
USE SCHEMA {{DB}}.INTAKE;

-- The first design called small helper procedures for authorisation and history. Each CALL costs a round of
-- compilation (a statement is 350 to 900 ms here), so both are inline now and the old helpers are removed.
DROP PROCEDURE IF EXISTS AUTHORIZE(VARCHAR, VARCHAR);
DROP PROCEDURE IF EXISTS LOG_HISTORY(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARIANT, VARIANT, VARCHAR, VARCHAR, VARCHAR);
DROP PROCEDURE IF EXISTS REFRESH_PATIENT(VARCHAR, DATE);

-- Registering a patient -------------------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE REGISTER_PATIENT(P_ACTOR VARCHAR, P_JSON VARCHAR, P_KEY VARCHAR, P_AS_OF DATE)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  doctors NUMBER DEFAULT 0;
  actor_role VARCHAR;
  replay VARIANT;
  pid VARCHAR;
  after VARIANT;
  outcome VARCHAR;
  result VARIANT;
BEGIN
  SELECT COUNT(*), MAX(SNOWFLAKE_ROLE) INTO :doctors, :actor_role FROM {{DB}}.SECURITY.APP_USER
    WHERE USER_ID = :P_ACTOR AND STATUS = 'ACTIVE' AND ROLE_CODE = 'DOCTOR';
  IF (doctors = 0) THEN
    RETURN OBJECT_CONSTRUCT('ok', FALSE, 'error', 'forbidden');
  END IF;
  IF (P_KEY IS NOT NULL) THEN
    SELECT RESULT INTO :replay FROM {{DB}}.INTAKE.REQUEST_LOG WHERE REQUEST_KEY = :P_KEY AND ACTOR_ID = :P_ACTOR;
    IF (replay IS NOT NULL) THEN
      RETURN replay;
    END IF;
  END IF;

  SELECT 'P-' || {{DB}}.CLINICAL.PATIENT_SEQ.NEXTVAL INTO :pid;
  INSERT INTO {{DB}}.CLINICAL.PATIENT
    (PATIENT_ID, SOURCE_ID, FULL_NAME, BIRTH_DATE, SEX, MARITAL_STATUS, CITY, STATE, PIN_CODE, PHONE,
     ENTERED_BY, ENTRY_SOURCE, UPDATED_AT, UPDATED_BY)
  SELECT :pid, 'manual-' || :pid, d:full_name::VARCHAR, TRY_TO_DATE(d:birth_date::VARCHAR), d:sex::VARCHAR,
         d:marital_status::VARCHAR, d:city::VARCHAR, d:state::VARCHAR, d:pin_code::VARCHAR, d:phone::VARCHAR,
         :P_ACTOR, 'MANUAL', SYSDATE(), :P_ACTOR
  FROM (SELECT PARSE_JSON(:P_JSON) AS d);

  INSERT INTO {{DB}}.SECURITY.PATIENT_ENTITLEMENT
    (ENTITLEMENT_ID, PATIENT_ID, USER_ID, SNOWFLAKE_ROLE, GRANTED_BY, GRANTED_AT)
  SELECT UUID_STRING(), :pid, :P_ACTOR, :actor_role, :P_ACTOR, SYSDATE();

  SELECT OBJECT_CONSTRUCT(*) INTO :after FROM {{DB}}.CLINICAL.PATIENT WHERE PATIENT_ID = :pid;
  INSERT INTO {{DB}}.CLINICAL.RECORD_HISTORY
    (HISTORY_ID, PATIENT_ID, ENTITY, RECORD_ID, OP, BEFORE_JSON, AFTER_JSON, ACTOR_ID, REASON, ENTRY_SOURCE, AT)
  SELECT UUID_STRING(), :pid, 'PATIENT', :pid, 'CREATE', NULL, :after, :P_ACTOR, NULL, 'MANUAL', SYSDATE();

  -- The new patient must be openable at once, so this one refresh is synchronous (no deletes: there is nothing yet).
  CALL {{DB}}.INTAKE.REFRESH_PATIENT(:pid, :P_AS_OF, TRUE) INTO :outcome;
  -- The background worker still owes this patient an embedding (similar-patient search), so queue that too.
  INSERT INTO {{DB}}.INTAKE.REFRESH_QUEUE (PATIENT_ID, ENQUEUED_AT) SELECT :pid, SYSDATE();

  result := OBJECT_CONSTRUCT('ok', TRUE, 'patient_id', :pid, 'record_id', :pid, 'version', 1);
  IF (P_KEY IS NOT NULL) THEN
    INSERT INTO {{DB}}.INTAKE.REQUEST_LOG SELECT :P_KEY, :P_ACTOR, :result, SYSDATE();
  END IF;
  RETURN result;
END;
$$;

-- Creating, editing, archiving and restoring a record -------------------------------------------------------------
CREATE OR REPLACE PROCEDURE WRITE_RECORD(
  P_ACTOR VARCHAR, P_ENTITY VARCHAR, P_OP VARCHAR, P_PATIENT_ID VARCHAR, P_RECORD_ID VARCHAR,
  P_VERSION NUMBER, P_JSON VARCHAR, P_KEY VARCHAR, P_REASON VARCHAR, P_AS_OF DATE, P_SOURCE VARCHAR)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  doctors NUMBER DEFAULT 0;
  entitled NUMBER DEFAULT 0;
  replay VARIANT;
  fq VARCHAR;
  idcol VARCHAR;
  prefix VARCHAR;
  rid VARCHAR;
  actor_name VARCHAR;
  current_version NUMBER;
  new_version NUMBER;
  drug_id VARCHAR;
  drug_display VARCHAR;
  typed_name VARCHAR;
  lab_known NUMBER DEFAULT 0;
  before VARIANT;
  after VARIANT;
  result VARIANT;
  source VARCHAR DEFAULT COALESCE(:P_SOURCE, 'MANUAL');
BEGIN
  -- One statement answers: is the actor an active doctor, do they hold this patient, and what is their name.
  SELECT COUNT(DISTINCT IFF(u.STATUS = 'ACTIVE' AND u.ROLE_CODE = 'DOCTOR', u.USER_ID, NULL)),
         COUNT(e.ENTITLEMENT_ID), MAX(u.DISPLAY_NAME)
    INTO :doctors, :entitled, :actor_name
    FROM {{DB}}.SECURITY.APP_USER u
    LEFT JOIN {{DB}}.SECURITY.PATIENT_ENTITLEMENT e
      ON e.USER_ID = u.USER_ID AND e.PATIENT_ID = :P_PATIENT_ID AND e.REVOKED_AT IS NULL
    WHERE u.USER_ID = :P_ACTOR;
  IF (doctors = 0) THEN
    RETURN OBJECT_CONSTRUCT('ok', FALSE, 'error', 'forbidden');
  END IF;
  IF (entitled = 0) THEN
    RETURN OBJECT_CONSTRUCT('ok', FALSE, 'error', 'denied');
  END IF;
  IF (P_KEY IS NOT NULL) THEN
    SELECT RESULT INTO :replay FROM {{DB}}.INTAKE.REQUEST_LOG WHERE REQUEST_KEY = :P_KEY AND ACTOR_ID = :P_ACTOR;
    IF (replay IS NOT NULL) THEN
      RETURN replay;
    END IF;
  END IF;

  -- Fixed lists, never taken from the caller: the table, its key column and the id prefix for new rows.
  fq := CASE P_ENTITY
          WHEN 'PATIENT' THEN '{{DB}}.CLINICAL.PATIENT' WHEN 'DIAGNOSIS' THEN '{{DB}}.CLINICAL.DIAGNOSIS'
          WHEN 'MEDICATION' THEN '{{DB}}.CLINICAL.MEDICATION' WHEN 'ALLERGY' THEN '{{DB}}.CLINICAL.ALLERGY'
          WHEN 'LAB_RESULT' THEN '{{DB}}.CLINICAL.LAB_RESULT' WHEN 'CLINICAL_NOTE' THEN '{{DB}}.CLINICAL.CLINICAL_NOTE'
          WHEN 'ENCOUNTER' THEN '{{DB}}.CLINICAL.ENCOUNTER' END;
  idcol := CASE P_ENTITY
             WHEN 'PATIENT' THEN 'PATIENT_ID' WHEN 'DIAGNOSIS' THEN 'DIAGNOSIS_ID' WHEN 'MEDICATION' THEN 'MEDICATION_ID'
             WHEN 'ALLERGY' THEN 'ALLERGY_ID' WHEN 'LAB_RESULT' THEN 'LAB_ID' WHEN 'CLINICAL_NOTE' THEN 'NOTE_ID'
             WHEN 'ENCOUNTER' THEN 'ENCOUNTER_ID' END;
  prefix := CASE P_ENTITY
              WHEN 'DIAGNOSIS' THEN 'DX-' WHEN 'MEDICATION' THEN 'RX-' WHEN 'ALLERGY' THEN 'ALG-'
              WHEN 'LAB_RESULT' THEN 'LAB-' WHEN 'CLINICAL_NOTE' THEN 'DOC-OP-' WHEN 'ENCOUNTER' THEN 'ENC-' END;
  IF (fq IS NULL OR P_OP NOT IN ('CREATE', 'UPDATE', 'ARCHIVE', 'RESTORE') OR (P_OP = 'CREATE' AND P_ENTITY = 'PATIENT')) THEN
    RETURN OBJECT_CONSTRUCT('ok', FALSE, 'error', 'invalid', 'detail', 'unsupported entity or operation');
  END IF;

  IF (P_OP = 'CREATE') THEN
    SELECT :prefix || {{DB}}.CLINICAL.RECORD_SEQ.NEXTVAL INTO :rid;
  ELSE
    rid := COALESCE(:P_RECORD_ID, :P_PATIENT_ID);
    -- The row must exist for this patient, and the caller's version must be current. One read gets both and the image.
    SELECT VERSION, OBJECT_CONSTRUCT(*) INTO :current_version, :before FROM IDENTIFIER(:fq)
      WHERE IDENTIFIER(:idcol) = :rid AND PATIENT_ID = :P_PATIENT_ID;
    IF (current_version IS NULL) THEN
      RETURN OBJECT_CONSTRUCT('ok', FALSE, 'error', 'not_found');
    END IF;
    IF (current_version <> :P_VERSION) THEN
      RETURN OBJECT_CONSTRUCT('ok', FALSE, 'error', 'conflict', 'current_version', current_version);
    END IF;
  END IF;

  -- Archive and restore are the same for every table ----------------------------------------------------------
  IF (P_OP = 'ARCHIVE') THEN
    UPDATE IDENTIFIER(:fq) SET IS_ARCHIVED = TRUE, ARCHIVED_AT = SYSDATE(), ARCHIVED_BY = :P_ACTOR,
           VERSION = VERSION + 1, UPDATED_AT = SYSDATE(), UPDATED_BY = :P_ACTOR
      WHERE IDENTIFIER(:idcol) = :rid AND PATIENT_ID = :P_PATIENT_ID;
  ELSEIF (P_OP = 'RESTORE') THEN
    UPDATE IDENTIFIER(:fq) SET IS_ARCHIVED = FALSE, ARCHIVED_AT = NULL, ARCHIVED_BY = NULL,
           VERSION = VERSION + 1, UPDATED_AT = SYSDATE(), UPDATED_BY = :P_ACTOR
      WHERE IDENTIFIER(:idcol) = :rid AND PATIENT_ID = :P_PATIENT_ID;

  -- Patient demographics ----------------------------------------------------------------------------------------
  ELSEIF (P_ENTITY = 'PATIENT') THEN
    UPDATE {{DB}}.CLINICAL.PATIENT t
      SET FULL_NAME = s.d:full_name::VARCHAR, BIRTH_DATE = TRY_TO_DATE(s.d:birth_date::VARCHAR), SEX = s.d:sex::VARCHAR,
          CITY = s.d:city::VARCHAR, STATE = s.d:state::VARCHAR, PIN_CODE = s.d:pin_code::VARCHAR, PHONE = s.d:phone::VARCHAR,
          VERSION = t.VERSION + 1, UPDATED_AT = SYSDATE(), UPDATED_BY = :P_ACTOR
      FROM (SELECT PARSE_JSON(:P_JSON) AS d) s
      WHERE t.PATIENT_ID = :P_PATIENT_ID;

  -- Diagnosis ---------------------------------------------------------------------------------------------------
  ELSEIF (P_ENTITY = 'DIAGNOSIS' AND P_OP = 'CREATE') THEN
    INSERT INTO {{DB}}.CLINICAL.DIAGNOSIS
      (DIAGNOSIS_ID, PATIENT_ID, CODE_SYSTEM, CODE, DESCRIPTION, ONSET_DATE, RESOLVED_DATE, IS_ACTIVE,
       ENTERED_BY, ENTRY_SOURCE, UPDATED_AT, UPDATED_BY)
    SELECT :rid, :P_PATIENT_ID, d:code_system::VARCHAR, d:code::VARCHAR, d:description::VARCHAR,
           TRY_TO_DATE(d:onset_date::VARCHAR), TRY_TO_DATE(d:resolved_date::VARCHAR),
           TRY_TO_DATE(d:resolved_date::VARCHAR) IS NULL, :P_ACTOR, :source, SYSDATE(), :P_ACTOR
    FROM (SELECT PARSE_JSON(:P_JSON) AS d);
  ELSEIF (P_ENTITY = 'DIAGNOSIS') THEN
    UPDATE {{DB}}.CLINICAL.DIAGNOSIS t
      SET CODE_SYSTEM = s.d:code_system::VARCHAR, CODE = s.d:code::VARCHAR, DESCRIPTION = s.d:description::VARCHAR,
          ONSET_DATE = TRY_TO_DATE(s.d:onset_date::VARCHAR), RESOLVED_DATE = TRY_TO_DATE(s.d:resolved_date::VARCHAR),
          IS_ACTIVE = TRY_TO_DATE(s.d:resolved_date::VARCHAR) IS NULL,
          VERSION = t.VERSION + 1, UPDATED_AT = SYSDATE(), UPDATED_BY = :P_ACTOR
      FROM (SELECT PARSE_JSON(:P_JSON) AS d) s
      WHERE t.DIAGNOSIS_ID = :rid AND t.PATIENT_ID = :P_PATIENT_ID;

  -- Medication: resolve the drug (brand or generic) against the knowledge base ------------------------------------
  ELSEIF (P_ENTITY = 'MEDICATION') THEN
    SELECT LOWER(TRIM(PARSE_JSON(:P_JSON):description::VARCHAR)) INTO :typed_name;
    SELECT MIN(n.DRUG_ID) INTO :drug_id
      FROM {{DB}}.KNOWLEDGE.DRUG_NAME_MAP n
      JOIN {{DB}}.KNOWLEDGE.DRUG dr ON dr.DRUG_ID = n.DRUG_ID AND dr.IN_CORPUS
      WHERE :typed_name = n.NAME_TEXT OR :typed_name LIKE n.NAME_TEXT || ' %';
    SELECT MIN(INITCAP(GENERIC_NAME)) INTO :drug_display FROM {{DB}}.KNOWLEDGE.DRUG WHERE DRUG_ID = :drug_id;
    IF (P_OP = 'CREATE') THEN
      INSERT INTO {{DB}}.CLINICAL.MEDICATION
        (MEDICATION_ID, PATIENT_ID, DESCRIPTION, DRUG_ID, DRUG_NAME, STRENGTH_TEXT, DOSE_TEXT, START_DATE, STOP_DATE,
         IS_ACTIVE, LAST_CHANGE_DATE, CHANGE_NOTE, REASON_DESCRIPTION, ENTERED_BY, ENTRY_SOURCE, UPDATED_AT, UPDATED_BY)
      SELECT :rid, :P_PATIENT_ID, TRIM(d:description::VARCHAR), :drug_id,
             COALESCE(:drug_display, TRIM(d:description::VARCHAR)), d:strength_text::VARCHAR, d:dose_text::VARCHAR,
             TRY_TO_DATE(d:start_date::VARCHAR), TRY_TO_DATE(d:stop_date::VARCHAR),
             TRY_TO_DATE(d:stop_date::VARCHAR) IS NULL, NULL, NULL, d:reason_description::VARCHAR,
             :P_ACTOR, :source, SYSDATE(), :P_ACTOR
      FROM (SELECT PARSE_JSON(:P_JSON) AS d);
    ELSE
      UPDATE {{DB}}.CLINICAL.MEDICATION t
        SET DESCRIPTION = TRIM(s.d:description::VARCHAR), DRUG_ID = :drug_id,
            DRUG_NAME = COALESCE(:drug_display, TRIM(s.d:description::VARCHAR)),
            STRENGTH_TEXT = s.d:strength_text::VARCHAR, DOSE_TEXT = s.d:dose_text::VARCHAR,
            START_DATE = TRY_TO_DATE(s.d:start_date::VARCHAR), STOP_DATE = TRY_TO_DATE(s.d:stop_date::VARCHAR),
            IS_ACTIVE = TRY_TO_DATE(s.d:stop_date::VARCHAR) IS NULL,
            REASON_DESCRIPTION = s.d:reason_description::VARCHAR,
            -- a changed dose, or a stop, is a medication change the timeline and "what changed" pick up
            LAST_CHANGE_DATE = CASE
              WHEN t.IS_ACTIVE AND TRY_TO_DATE(s.d:stop_date::VARCHAR) IS NOT NULL THEN TRY_TO_DATE(s.d:stop_date::VARCHAR)
              WHEN t.DOSE_TEXT IS DISTINCT FROM s.d:dose_text::VARCHAR THEN :P_AS_OF
              ELSE t.LAST_CHANGE_DATE END,
            CHANGE_NOTE = CASE
              WHEN t.IS_ACTIVE AND TRY_TO_DATE(s.d:stop_date::VARCHAR) IS NOT NULL
                THEN COALESCE(NULLIF(s.d:change_note::VARCHAR, ''), 'Stopped')
              WHEN t.DOSE_TEXT IS DISTINCT FROM s.d:dose_text::VARCHAR
                THEN COALESCE(NULLIF(s.d:change_note::VARCHAR, ''),
                              'Dose changed from ' || COALESCE(t.DOSE_TEXT, 'not recorded') || ' to ' || COALESCE(s.d:dose_text::VARCHAR, 'not recorded'))
              ELSE t.CHANGE_NOTE END,
            VERSION = t.VERSION + 1, UPDATED_AT = SYSDATE(), UPDATED_BY = :P_ACTOR
        FROM (SELECT PARSE_JSON(:P_JSON) AS d) s
        WHERE t.MEDICATION_ID = :rid AND t.PATIENT_ID = :P_PATIENT_ID;
    END IF;

  -- Allergy -----------------------------------------------------------------------------------------------------
  ELSEIF (P_ENTITY = 'ALLERGY' AND P_OP = 'CREATE') THEN
    INSERT INTO {{DB}}.CLINICAL.ALLERGY
      (ALLERGY_ID, PATIENT_ID, SUBSTANCE, REACTION, SEVERITY, IS_ACTIVE, RECORDED_ON, SOURCE,
       ENTERED_BY, ENTRY_SOURCE, UPDATED_AT, UPDATED_BY)
    SELECT :rid, :P_PATIENT_ID, TRIM(d:substance::VARCHAR), d:reaction::VARCHAR, d:severity::VARCHAR,
           COALESCE(d:is_active::BOOLEAN, TRUE), COALESCE(TRY_TO_DATE(d:recorded_on::VARCHAR), :P_AS_OF), :source,
           :P_ACTOR, :source, SYSDATE(), :P_ACTOR
    FROM (SELECT PARSE_JSON(:P_JSON) AS d);
  ELSEIF (P_ENTITY = 'ALLERGY') THEN
    UPDATE {{DB}}.CLINICAL.ALLERGY t
      SET SUBSTANCE = TRIM(s.d:substance::VARCHAR), REACTION = s.d:reaction::VARCHAR, SEVERITY = s.d:severity::VARCHAR,
          IS_ACTIVE = COALESCE(s.d:is_active::BOOLEAN, TRUE),
          VERSION = t.VERSION + 1, UPDATED_AT = SYSDATE(), UPDATED_BY = :P_ACTOR
      FROM (SELECT PARSE_JSON(:P_JSON) AS d) s
      WHERE t.ALLERGY_ID = :rid AND t.PATIENT_ID = :P_PATIENT_ID;

  -- Laboratory result: unit, range and flag come from LAB_REFERENCE, never from the caller ---------------------------
  ELSEIF (P_ENTITY = 'LAB_RESULT') THEN
    SELECT COUNT(*) INTO :lab_known FROM {{DB}}.CLINICAL.LAB_REFERENCE WHERE LOINC_CODE = PARSE_JSON(:P_JSON):loinc_code::VARCHAR;
    IF (lab_known = 0) THEN
      RETURN OBJECT_CONSTRUCT('ok', FALSE, 'error', 'invalid', 'detail', 'unknown test');
    END IF;
    IF (P_OP = 'CREATE') THEN
      INSERT INTO {{DB}}.CLINICAL.LAB_RESULT
        (LAB_ID, PATIENT_ID, ENCOUNTER_ID, OBSERVED_AT, LOINC_CODE, TEST_NAME, VALUE_NUM, UNIT, REF_LOW, REF_HIGH,
         ABNORMAL_FLAG, CATEGORY, ENTERED_BY, ENTRY_SOURCE, UPDATED_AT, UPDATED_BY)
      SELECT :rid, :P_PATIENT_ID, NULLIF(d:encounter_id::VARCHAR, ''), TRY_TO_TIMESTAMP_NTZ(d:observed_at::VARCHAR),
             ref.LOINC_CODE, ref.TEST_NAME, d:value_num::NUMBER(18,4), ref.UNIT, ref.REF_LOW, ref.REF_HIGH,
             CASE WHEN ref.REF_LOW IS NULL AND ref.REF_HIGH IS NULL THEN NULL
                  WHEN d:value_num::NUMBER(18,4) < ref.REF_LOW THEN 'LOW'
                  WHEN d:value_num::NUMBER(18,4) > ref.REF_HIGH THEN 'HIGH' ELSE 'NORMAL' END,
             'laboratory', :P_ACTOR, :source, SYSDATE(), :P_ACTOR
      FROM (SELECT PARSE_JSON(:P_JSON) AS d) j
      JOIN {{DB}}.CLINICAL.LAB_REFERENCE ref ON ref.LOINC_CODE = j.d:loinc_code::VARCHAR;
    ELSE
      UPDATE {{DB}}.CLINICAL.LAB_RESULT t
        SET OBSERVED_AT = TRY_TO_TIMESTAMP_NTZ(s.d:observed_at::VARCHAR), LOINC_CODE = ref.LOINC_CODE,
            TEST_NAME = ref.TEST_NAME, VALUE_NUM = s.d:value_num::NUMBER(18,4), UNIT = ref.UNIT,
            REF_LOW = ref.REF_LOW, REF_HIGH = ref.REF_HIGH,
            ABNORMAL_FLAG = CASE WHEN ref.REF_LOW IS NULL AND ref.REF_HIGH IS NULL THEN NULL
                                 WHEN s.d:value_num::NUMBER(18,4) < ref.REF_LOW THEN 'LOW'
                                 WHEN s.d:value_num::NUMBER(18,4) > ref.REF_HIGH THEN 'HIGH' ELSE 'NORMAL' END,
            VERSION = t.VERSION + 1, UPDATED_AT = SYSDATE(), UPDATED_BY = :P_ACTOR
        FROM (SELECT PARSE_JSON(:P_JSON) AS d) s
        JOIN {{DB}}.CLINICAL.LAB_REFERENCE ref ON ref.LOINC_CODE = s.d:loinc_code::VARCHAR
        WHERE t.LAB_ID = :rid AND t.PATIENT_ID = :P_PATIENT_ID;
    END IF;

  -- Clinical note -------------------------------------------------------------------------------------------------
  ELSEIF (P_ENTITY = 'CLINICAL_NOTE' AND P_OP = 'CREATE') THEN
    INSERT INTO {{DB}}.CLINICAL.CLINICAL_NOTE
      (NOTE_ID, PATIENT_ID, ENCOUNTER_ID, NOTE_TYPE, TITLE, NOTE_DATE, AUTHOR, BODY, CONTAINS_INJECTION,
       ENTERED_BY, ENTRY_SOURCE, UPDATED_AT, UPDATED_BY)
    SELECT :rid, :P_PATIENT_ID, NULLIF(d:encounter_id::VARCHAR, ''), COALESCE(d:note_type::VARCHAR, 'OUTPATIENT_NOTE'),
           TRIM(d:title::VARCHAR), COALESCE(TRY_TO_DATE(d:note_date::VARCHAR), :P_AS_OF), :actor_name, d:body::VARCHAR, FALSE,
           :P_ACTOR, :source, SYSDATE(), :P_ACTOR
    FROM (SELECT PARSE_JSON(:P_JSON) AS d);
  ELSEIF (P_ENTITY = 'CLINICAL_NOTE') THEN
    UPDATE {{DB}}.CLINICAL.CLINICAL_NOTE t
      SET NOTE_TYPE = COALESCE(s.d:note_type::VARCHAR, t.NOTE_TYPE), TITLE = TRIM(s.d:title::VARCHAR),
          NOTE_DATE = COALESCE(TRY_TO_DATE(s.d:note_date::VARCHAR), t.NOTE_DATE), BODY = s.d:body::VARCHAR,
          VERSION = t.VERSION + 1, UPDATED_AT = SYSDATE(), UPDATED_BY = :P_ACTOR
      FROM (SELECT PARSE_JSON(:P_JSON) AS d) s
      WHERE t.NOTE_ID = :rid AND t.PATIENT_ID = :P_PATIENT_ID;

  -- Encounter (a visit) -------------------------------------------------------------------------------------------
  ELSEIF (P_ENTITY = 'ENCOUNTER' AND P_OP = 'CREATE') THEN
    INSERT INTO {{DB}}.CLINICAL.ENCOUNTER
      (ENCOUNTER_ID, PATIENT_ID, STARTED_AT, ENDED_AT, ENCOUNTER_CLASS, VISIT_KIND, DESCRIPTION, REASON_DESCRIPTION,
       ENTERED_BY, ENTRY_SOURCE, UPDATED_AT, UPDATED_BY)
    SELECT :rid, :P_PATIENT_ID, TRY_TO_TIMESTAMP_NTZ(d:started_at::VARCHAR), TRY_TO_TIMESTAMP_NTZ(d:ended_at::VARCHAR),
           CASE d:visit_kind::VARCHAR WHEN 'EMERGENCY' THEN 'emergency' WHEN 'HOSPITALIZATION' THEN 'inpatient' ELSE 'outpatient' END,
           d:visit_kind::VARCHAR, d:description::VARCHAR, d:reason_description::VARCHAR,
           :P_ACTOR, :source, SYSDATE(), :P_ACTOR
    FROM (SELECT PARSE_JSON(:P_JSON) AS d);
  ELSEIF (P_ENTITY = 'ENCOUNTER') THEN
    UPDATE {{DB}}.CLINICAL.ENCOUNTER t
      SET STARTED_AT = TRY_TO_TIMESTAMP_NTZ(s.d:started_at::VARCHAR), ENDED_AT = TRY_TO_TIMESTAMP_NTZ(s.d:ended_at::VARCHAR),
          ENCOUNTER_CLASS = CASE s.d:visit_kind::VARCHAR WHEN 'EMERGENCY' THEN 'emergency' WHEN 'HOSPITALIZATION' THEN 'inpatient' ELSE 'outpatient' END,
          VISIT_KIND = s.d:visit_kind::VARCHAR, DESCRIPTION = s.d:description::VARCHAR,
          REASON_DESCRIPTION = s.d:reason_description::VARCHAR,
          VERSION = t.VERSION + 1, UPDATED_AT = SYSDATE(), UPDATED_BY = :P_ACTOR
      FROM (SELECT PARSE_JSON(:P_JSON) AS d) s
      WHERE t.ENCOUNTER_ID = :rid AND t.PATIENT_ID = :P_PATIENT_ID;
  END IF;

  SELECT VERSION, OBJECT_CONSTRUCT(*) INTO :new_version, :after FROM IDENTIFIER(:fq)
    WHERE IDENTIFIER(:idcol) = :rid AND PATIENT_ID = :P_PATIENT_ID;
  INSERT INTO {{DB}}.CLINICAL.RECORD_HISTORY
    (HISTORY_ID, PATIENT_ID, ENTITY, RECORD_ID, OP, BEFORE_JSON, AFTER_JSON, ACTOR_ID, REASON, ENTRY_SOURCE, AT)
  SELECT UUID_STRING(), :P_PATIENT_ID, :P_ENTITY, :rid, :P_OP, :before, :after, :P_ACTOR, :P_REASON, :source, SYSDATE();
  -- The read models (worklist, timeline, latest labs) are rebuilt by the API's background worker, which saves the
  -- caller about six seconds; this row makes sure it happens even if the API restarts first.
  INSERT INTO {{DB}}.INTAKE.REFRESH_QUEUE (PATIENT_ID, ENQUEUED_AT) SELECT :P_PATIENT_ID, SYSDATE();

  result := OBJECT_CONSTRUCT('ok', TRUE, 'patient_id', :P_PATIENT_ID, 'record_id', :rid, 'version', :new_version);
  IF (P_KEY IS NOT NULL) THEN
    INSERT INTO {{DB}}.INTAKE.REQUEST_LOG SELECT :P_KEY, :P_ACTOR, :result, SYSDATE();
  END IF;
  RETURN result;
END;
$$;

-- The API's service role may call the entry points only; helpers stay internal.
GRANT USAGE ON PROCEDURE {{DB}}.INTAKE.REGISTER_PATIENT(VARCHAR, VARCHAR, VARCHAR, DATE) TO ROLE MED_API;
GRANT USAGE ON PROCEDURE {{DB}}.INTAKE.WRITE_RECORD(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, NUMBER, VARCHAR, VARCHAR, VARCHAR, DATE, VARCHAR) TO ROLE MED_API;
