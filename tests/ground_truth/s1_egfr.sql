-- Ground truth: S1 (P-1042) eGFR (LOINC 33914-3), newest first. The first row is the "latest" value and the
-- second the "previous" one shown on the overview and in the safety review.
SELECT VALUE_NUM, OBSERVED_AT::DATE AS OBSERVED_ON
FROM CLINICAL.LAB_RESULT
WHERE PATIENT_ID = 'P-1042' AND LOINC_CODE = '33914-3'
ORDER BY OBSERVED_AT DESC, LAB_ID DESC;
