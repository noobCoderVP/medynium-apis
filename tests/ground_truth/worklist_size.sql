-- Ground truth: how many patients the signed-in user may see. Run as that user's own role, so the row access
-- policy on CLINICAL.PATIENT does the scoping. Compared with GET /dashboard utilization.patients.
SELECT COUNT(*) AS N FROM CLINICAL.PATIENT;
