-- Ground truth: S1 (P-1042) active medications. Compared with GET /patients/P-1042/medications and with the
-- "current medications" answer from the lookup route.
SELECT DRUG_NAME
FROM CLINICAL.MEDICATION
WHERE PATIENT_ID = 'P-1042' AND IS_ACTIVE
ORDER BY DRUG_NAME;
