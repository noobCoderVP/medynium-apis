-- 20_transform_clinical.sql: RAW -> CLINICAL. Run as MED_ADMIN. Idempotent: TRUNCATE + INSERT keeps comments
-- and the row access policy. Re-run 21_seed_scenarios.sql afterwards (it adds the hand-seeded patients).
--
-- Id scheme: generated rows use high numbers (P-2001.., ENC-100001.., ...) in a stable sort order so reruns give
-- the same ids; the seeded scenarios keep fixed low ids (P-1042, ENC-20931, ...) and never collide.
USE ROLE MED_ADMIN;
USE WAREHOUSE {{WH}};
USE SCHEMA {{DB}}.CLINICAL;

-- Reference ranges for the demo tests (Synthea supplies none) -----------------------------------
MERGE INTO LAB_REFERENCE t USING (
  SELECT * FROM VALUES
    ('33914-3','eGFR','Glomerular filtration rate (eGFR)','mL/min/1.73 m²',60,NULL,'Below 60 suggests reduced kidney function'),
    ('38483-4','Creatinine','Creatinine','mg/dL',0.6,1.3,'Adult reference range'),
    ('4548-4','HbA1c','Haemoglobin A1c','%',NULL,7.0,'Treatment target for diabetes'),
    ('6298-4','Potassium','Potassium','mmol/L',3.5,5.0,'Adult reference range'),
    ('2951-2','Sodium','Sodium','mmol/L',135,145,'Adult reference range'),
    ('718-7','Haemoglobin','Haemoglobin','g/dL',12.0,17.0,'Adult reference range'),
    ('3016-3','TSH','Thyrotropin (TSH)','mIU/L',0.4,4.0,'Adult reference range'),
    ('18262-6','LDL','LDL cholesterol','mg/dL',NULL,100,'Optimal below 100'),
    ('2339-0','Glucose','Glucose','mg/dL',70,99,'Fasting reference range'),
    ('3024-7','Free T4','Thyroxine (free T4)','ng/dL',0.8,1.8,'Adult reference range'),
    ('3084-1','Uric acid','Uric acid','mg/dL',2.4,6.0,'Adult reference range'),
    ('2075-0','Chloride','Chloride','mmol/L',98,107,'Adult reference range'),
    ('3091-6','Blood urea','Urea','mg/dL',15,40,'Adult reference range'),
    ('777-3','Platelets','Platelet count','10^3/uL',150,410,'Adult reference range'),
    ('2571-8','Triglycerides','Triglycerides','mg/dL',NULL,150,'Normal below 150'),
    ('2085-9','HDL','HDL cholesterol','mg/dL',50,NULL,'Desirable above 50 in women'),
    ('6690-2','WBC','Leukocytes (WBC)','10^3/uL',4.0,11.0,'Adult reference range'),
    ('2093-3','Total cholesterol','Total cholesterol','mg/dL',NULL,200,'Desirable below 200')
  AS v(LOINC_CODE, SHORT_NAME, TEST_NAME, UNIT, REF_LOW, REF_HIGH, SOURCE_NOTE)
) s ON t.LOINC_CODE = s.LOINC_CODE
WHEN MATCHED THEN UPDATE SET SHORT_NAME = s.SHORT_NAME, TEST_NAME = s.TEST_NAME, UNIT = s.UNIT,
  REF_LOW = s.REF_LOW, REF_HIGH = s.REF_HIGH, SOURCE_NOTE = s.SOURCE_NOTE
WHEN NOT MATCHED THEN INSERT (LOINC_CODE, SHORT_NAME, TEST_NAME, UNIT, REF_LOW, REF_HIGH, SOURCE_NOTE)
  VALUES (s.LOINC_CODE, s.SHORT_NAME, s.TEST_NAME, s.UNIT, s.REF_LOW, s.REF_HIGH, s.SOURCE_NOTE);

TRUNCATE TABLE CLAIM;
TRUNCATE TABLE PROCEDURE;
TRUNCATE TABLE LAB_RESULT;
TRUNCATE TABLE MEDICATION;
TRUNCATE TABLE DIAGNOSIS;
TRUNCATE TABLE ENCOUNTER;
TRUNCATE TABLE PROVIDER;
TRUNCATE TABLE PATIENT;

-- Patients (alive only) ---------------------------------------------------------------------------
INSERT INTO PATIENT (PATIENT_ID, SOURCE_ID, FULL_NAME, BIRTH_DATE, DEATH_DATE, SEX, MARITAL_STATUS, CITY, STATE, PIN_CODE, PHONE)
SELECT 'P-' || (2000 + ROW_NUMBER() OVER (ORDER BY ID)), ID, FULL_NAME, TRY_TO_DATE(BIRTHDATE), NULL,
       GENDER, MARITAL, CITY, STATE, PIN_CODE, PHONE
FROM {{DB}}.RAW.PATIENTS
WHERE DEATHDATE IS NULL;

CREATE OR REPLACE TEMPORARY TABLE PMAP AS SELECT SOURCE_ID, PATIENT_ID FROM PATIENT;

INSERT INTO PROVIDER (PROVIDER_ID, NAME, SPECIALITY, ORGANIZATION_NAME)
SELECT 'PRV-' || LPAD(ROW_NUMBER() OVER (ORDER BY p.ID)::VARCHAR, 4, '0'), p.NAME, p.SPECIALITY, o.NAME
FROM {{DB}}.RAW.PROVIDERS p LEFT JOIN {{DB}}.RAW.ORGANIZATIONS o ON o.ID = p.ORGANIZATION;

CREATE OR REPLACE TEMPORARY TABLE PRVMAP AS
SELECT p.ID AS SOURCE_ID, 'PRV-' || LPAD(ROW_NUMBER() OVER (ORDER BY p.ID)::VARCHAR, 4, '0') AS PROVIDER_ID
FROM {{DB}}.RAW.PROVIDERS p;

-- Encounters --------------------------------------------------------------------------------------
INSERT INTO ENCOUNTER (ENCOUNTER_ID, SOURCE_ID, PATIENT_ID, STARTED_AT, ENDED_AT, ENCOUNTER_CLASS, VISIT_KIND, CODE,
                       DESCRIPTION, PROVIDER_ID, REASON_CODE, REASON_DESCRIPTION, BASE_COST_INR, TOTAL_CLAIM_COST_INR, PAYER_COVERAGE_INR)
SELECT 'ENC-' || (100000 + ROW_NUMBER() OVER (ORDER BY e."START", e.ID)), e.ID, pm.PATIENT_ID,
       TRY_TO_TIMESTAMP_NTZ(REPLACE(e."START", 'Z', '')), TRY_TO_TIMESTAMP_NTZ(REPLACE(e.STOP, 'Z', '')),
       e.ENCOUNTERCLASS,
       CASE WHEN e.ENCOUNTERCLASS = 'emergency' THEN 'EMERGENCY'
            WHEN e.ENCOUNTERCLASS IN ('inpatient', 'snf', 'hospice') THEN 'HOSPITALIZATION'
            ELSE 'OUTPATIENT' END,
       e.CODE, e.DESCRIPTION, prv.PROVIDER_ID, e.REASONCODE, e.REASONDESCRIPTION,
       TRY_TO_DECIMAL(e.BASE_ENCOUNTER_COST, 12, 2), TRY_TO_DECIMAL(e.TOTAL_CLAIM_COST, 12, 2), TRY_TO_DECIMAL(e.PAYER_COVERAGE, 12, 2)
FROM {{DB}}.RAW.ENCOUNTERS e
JOIN PMAP pm ON pm.SOURCE_ID = e.PATIENT
LEFT JOIN PRVMAP prv ON prv.SOURCE_ID = e.PROVIDER;

CREATE OR REPLACE TEMPORARY TABLE EMAP AS SELECT SOURCE_ID, ENCOUNTER_ID FROM ENCOUNTER;

-- Diagnoses ---------------------------------------------------------------------------------------
INSERT INTO DIAGNOSIS (DIAGNOSIS_ID, PATIENT_ID, ENCOUNTER_ID, CODE_SYSTEM, CODE, DESCRIPTION, ONSET_DATE, RESOLVED_DATE, IS_ACTIVE)
SELECT 'DX-' || (100000 + ROW_NUMBER() OVER (ORDER BY pm.PATIENT_ID, c."START", c.CODE)), pm.PATIENT_ID, em.ENCOUNTER_ID,
       c.SYSTEM, c.CODE, REGEXP_REPLACE(c.DESCRIPTION, ' \\((disorder|finding|situation)\\)$', ''),
       TRY_TO_DATE(LEFT(c."START", 10)), TRY_TO_DATE(LEFT(c.STOP, 10)), c.STOP IS NULL
FROM {{DB}}.RAW.CONDITIONS c
JOIN PMAP pm ON pm.SOURCE_ID = c.PATIENT
LEFT JOIN EMAP em ON em.SOURCE_ID = c.ENCOUNTER
WHERE c.DESCRIPTION LIKE '%(disorder)';  -- Synthea also stores findings and situations (employment, social); not diagnoses

-- Medications: name, strength and dose text are parsed from the Synthea description. DRUG_ID is linked
-- later by 31_link_medications.sql, once KNOWLEDGE.DRUG exists.
INSERT INTO MEDICATION (MEDICATION_ID, PATIENT_ID, ENCOUNTER_ID, RXNORM_CODE, DESCRIPTION, DRUG_ID, DRUG_NAME, STRENGTH_TEXT, DOSE_TEXT,
                        START_DATE, STOP_DATE, IS_ACTIVE, DISPENSES, TOTAL_COST_INR, REASON_CODE, REASON_DESCRIPTION)
WITH m AS (
  SELECT pm.PATIENT_ID, em.ENCOUNTER_ID, r.*,
         -- name = text before the first strength, minus any "12 HR " / "120 ACTUAT " prefix and its adjectives
         TRIM(REGEXP_REPLACE(REGEXP_REPLACE(r.DESCRIPTION, '[ ]*[0-9.]+ (MG|MCG|UNT|G|MEQ)(/[A-Z0-9.]+)?.*$', ''),
                             '^.*[0-9] (HR|ML|ACTUAT) ', '')) AS NAME_RAW,
         REGEXP_SUBSTR(r.DESCRIPTION, '[0-9.]+ (MG|MCG|UNT|G|MEQ)(/[A-Z0-9.]+)?.*$') AS FROM_STRENGTH
  FROM {{DB}}.RAW.MEDICATIONS r
  JOIN PMAP pm ON pm.SOURCE_ID = r.PATIENT
  LEFT JOIN EMAP em ON em.SOURCE_ID = r.ENCOUNTER
)
SELECT 'RX-' || (100000 + ROW_NUMBER() OVER (ORDER BY PATIENT_ID, "START", CODE)), PATIENT_ID, ENCOUNTER_ID, CODE, DESCRIPTION, NULL,
       UPPER(LEFT(NAME_RAW, 1)) || LOWER(SUBSTR(NAME_RAW, 2)),
       REGEXP_SUBSTR(DESCRIPTION, '[0-9.]+ (MG|MCG|UNT|G|MEQ)(/[A-Z0-9.]+)?'),
       FROM_STRENGTH,
       TRY_TO_DATE(LEFT("START", 10)), TRY_TO_DATE(LEFT(STOP, 10)), STOP IS NULL,
       TRY_TO_NUMBER(DISPENSES), TRY_TO_DECIMAL(TOTALCOST, 12, 2), REASONCODE, REASONDESCRIPTION
FROM m;

-- Lab results: numeric and text values, units normalised, reference range and flag from LAB_REFERENCE.
INSERT INTO LAB_RESULT (LAB_ID, PATIENT_ID, ENCOUNTER_ID, OBSERVED_AT, LOINC_CODE, TEST_NAME, VALUE_NUM, VALUE_TEXT, UNIT,
                        REF_LOW, REF_HIGH, ABNORMAL_FLAG, CATEGORY)
WITH o AS (
  SELECT pm.PATIENT_ID, em.ENCOUNTER_ID, r.CODE, r.DESCRIPTION, r.DATE, r.CATEGORY,
         IFF(r.TYPE = 'numeric', TRY_TO_DECIMAL(r.VALUE, 18, 4), NULL) AS VALUE_NUM,
         IFF(r.TYPE = 'numeric', NULL, r.VALUE) AS VALUE_TEXT,
         REPLACE(REPLACE(r.UNITS, '{1.73_m2}', '1.73 m²'), '{', '') AS UNIT
  FROM {{DB}}.RAW.OBSERVATIONS r
  JOIN PMAP pm ON pm.SOURCE_ID = r.PATIENT
  LEFT JOIN EMAP em ON em.SOURCE_ID = r.ENCOUNTER
)
SELECT 'LAB-' || (100000 + ROW_NUMBER() OVER (ORDER BY o.PATIENT_ID, o.DATE, o.CODE)), o.PATIENT_ID, o.ENCOUNTER_ID,
       TRY_TO_TIMESTAMP_NTZ(REPLACE(o.DATE, 'Z', '')), o.CODE, COALESCE(ref.TEST_NAME, o.DESCRIPTION), o.VALUE_NUM, o.VALUE_TEXT,
       COALESCE(NULLIF(o.UNIT, ''), ref.UNIT), ref.REF_LOW, ref.REF_HIGH,
       CASE WHEN o.VALUE_NUM IS NULL OR (ref.REF_LOW IS NULL AND ref.REF_HIGH IS NULL) THEN NULL
            WHEN ref.REF_LOW IS NOT NULL AND o.VALUE_NUM < ref.REF_LOW THEN 'LOW'
            WHEN ref.REF_HIGH IS NOT NULL AND o.VALUE_NUM > ref.REF_HIGH THEN 'HIGH'
            ELSE 'NORMAL' END,
       o.CATEGORY
FROM o LEFT JOIN LAB_REFERENCE ref ON ref.LOINC_CODE = o.CODE;

-- Procedures --------------------------------------------------------------------------------------
INSERT INTO PROCEDURE (PROCEDURE_ID, PATIENT_ID, ENCOUNTER_ID, CODE_SYSTEM, CODE, DESCRIPTION, PERFORMED_AT, BASE_COST_INR, REASON_CODE, REASON_DESCRIPTION)
SELECT 'PRC-' || (100000 + ROW_NUMBER() OVER (ORDER BY pm.PATIENT_ID, r."START", r.CODE)), pm.PATIENT_ID, em.ENCOUNTER_ID,
       r.SYSTEM, r.CODE, r.DESCRIPTION, TRY_TO_TIMESTAMP_NTZ(REPLACE(r."START", 'Z', '')), TRY_TO_DECIMAL(r.BASE_COST, 12, 2),
       r.REASONCODE, r.REASONDESCRIPTION
FROM {{DB}}.RAW.PROCEDURES r
JOIN PMAP pm ON pm.SOURCE_ID = r.PATIENT
LEFT JOIN EMAP em ON em.SOURCE_ID = r.ENCOUNTER;

-- Claims: Synthea claim rows carry no amounts; they come from the transactions.
--   billed      = sum of CHARGE (AMOUNT column)
--   paid        = sum of PAYMENT (PAYMENTS column; payer and patient)
--   approved    = payments minus the part the patient paid (TRANSFERIN = patient responsibility)
--   outstanding = billed - paid
-- A claim row links to an encounter through APPOINTMENTID; one encounter can have up to three claims.
INSERT INTO CLAIM (CLAIM_ID, SOURCE_ID, PATIENT_ID, ENCOUNTER_ID, PROVIDER_ID, SERVICE_DATE, SERVICE_TEXT, STATUS,
                   BILLED_INR, APPROVED_INR, OUTSTANDING_INR, PRIMARY_DIAGNOSIS_CODE)
WITH tx AS (
  SELECT CLAIMID,
         SUM(IFF(TYPE = 'CHARGE', TRY_TO_DECIMAL(AMOUNT, 18, 2), 0)) AS BILLED,
         SUM(IFF(TYPE = 'PAYMENT', TRY_TO_DECIMAL(PAYMENTS, 18, 2), 0)) AS PAID,
         SUM(IFF(TYPE = 'TRANSFERIN', TRY_TO_DECIMAL(AMOUNT, 18, 2), 0)) AS PATIENT_SHARE
  FROM {{DB}}.RAW.CLAIMS_TRANSACTIONS GROUP BY CLAIMID
), c AS (
  SELECT cl.*, pm.PATIENT_ID AS PID, em.ENCOUNTER_ID AS EID, prv.PROVIDER_ID AS PRVID, tx.BILLED, tx.PAID, tx.PATIENT_SHARE,
         GREATEST(0, COALESCE(tx.PAID, 0) - COALESCE(tx.PATIENT_SHARE, 0)) AS APPROVED
  FROM {{DB}}.RAW.CLAIMS cl
  JOIN PMAP pm ON pm.SOURCE_ID = cl.PATIENTID
  LEFT JOIN EMAP em ON em.SOURCE_ID = cl.APPOINTMENTID
  LEFT JOIN PRVMAP prv ON prv.SOURCE_ID = cl.PROVIDERID
  LEFT JOIN tx ON tx.CLAIMID = cl.ID
)
SELECT 'CLM-' || (100000 + ROW_NUMBER() OVER (ORDER BY c.PID, c.SERVICEDATE, c.ID)), c.ID, c.PID, c.EID, c.PRVID,
       TRY_TO_DATE(LEFT(c.SERVICEDATE, 10)), enc.DESCRIPTION,
       CASE WHEN GREATEST(0, COALESCE(c.BILLED, 0) - COALESCE(c.PAID, 0)) > 0.005 THEN 'SUBMITTED'
            WHEN c.APPROVED <= 0.005 THEN 'SELF_PAY'
            WHEN c.APPROVED >= c.BILLED - 0.005 THEN 'APPROVED'
            ELSE 'PARTIAL' END,
       COALESCE(c.BILLED, 0), c.APPROVED, GREATEST(0, COALESCE(c.BILLED, 0) - COALESCE(c.PAID, 0)), c.DIAGNOSIS1
FROM c LEFT JOIN ENCOUNTER enc ON enc.ENCOUNTER_ID = c.EID;
