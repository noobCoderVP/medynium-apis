"""Generate about 20 clinical notes from the structured tables (D-9), so a note never contradicts the record.

Picks emergency, inpatient and outpatient encounters of generated patients (deterministic order) and writes a
templated note from that patient's own facts. Idempotent: MERGE by NOTE_ID. The seeded notes (S1 to S5) come
from data/seed_scenarios.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sfadmin import build_vars, connect  # noqa: E402

TEMPLATES = {
    "EMERGENCY": ("ED_NOTE", "Emergency department note",
                  "{age}-year-old {sex} presented with {reason}. Assessment done and investigations sent. {meds} Observed and advised follow-up."),
    "HOSPITALIZATION": ("DISCHARGE_SUMMARY", "Discharge summary",
                        "{age}-year-old {sex} admitted with {reason}. Treated and discharged in stable condition. {meds} Follow-up advised."),
    "OUTPATIENT": ("OUTPATIENT_NOTE", "Outpatient note",
                   "{age}-year-old {sex} seen for {reason}. {meds} Reviewed and plan unchanged; follow-up as scheduled."),
}  # fmt: skip


def main() -> None:
    conn = connect("MED_ADMIN", build_vars()["DB"])
    cur = conn.cursor()
    cur.execute(f"USE WAREHOUSE {build_vars()['WH']}")
    cur.execute(
        """
        WITH ranked AS (
          SELECT e.ENCOUNTER_ID, e.PATIENT_ID, e.VISIT_KIND, e.STARTED_AT::DATE AS D,
                 COALESCE(e.REASON_DESCRIPTION, e.DESCRIPTION) AS REASON,
                 p.SEX, FLOOR(DATEDIFF('day', p.BIRTH_DATE, e.STARTED_AT::DATE) / 365.25) AS AGE,
                 ROW_NUMBER() OVER (PARTITION BY e.VISIT_KIND ORDER BY HASH(e.ENCOUNTER_ID)) AS RN
          FROM CLINICAL.ENCOUNTER e JOIN CLINICAL.PATIENT p ON p.PATIENT_ID = e.PATIENT_ID
          WHERE e.PATIENT_ID LIKE 'P-2%%' AND e.STARTED_AT::DATE <= %s
            AND e.STARTED_AT::DATE >= DATEADD('month', -9, %s::DATE)
        )
        SELECT * FROM ranked WHERE (VISIT_KIND = 'EMERGENCY' AND RN <= 5) OR (VISIT_KIND = 'HOSPITALIZATION' AND RN <= 6)
           OR (VISIT_KIND = 'OUTPATIENT' AND RN <= 9) ORDER BY ENCOUNTER_ID
        """,
        (build_vars()["AS_OF"], build_vars()["AS_OF"]),
    )
    rows = cur.fetchall()
    for enc_id, patient_id, kind, day, reason, sex, age, _ in rows:
        cur.execute(
            "SELECT LISTAGG(DRUG_NAME, ', ') WITHIN GROUP (ORDER BY DRUG_NAME) FROM CLINICAL.MEDICATION "
            "WHERE PATIENT_ID = %s AND IS_ACTIVE",
            (patient_id,),
        )
        meds = cur.fetchone()[0]
        note_type, title, template = TEMPLATES[kind]
        body = template.format(
            age=int(age), sex="man" if sex == "M" else "woman", reason=str(reason).lower(),
            meds=f"Current medicines: {meds}." if meds else "No active medicines on record.",
        )  # fmt: skip
        note_id = f"DOC-{note_type[:2]}-{enc_id[4:]}"
        cur.execute(
            "MERGE INTO CLINICAL.CLINICAL_NOTE t USING (SELECT %s AS NOTE_ID) s ON t.NOTE_ID = s.NOTE_ID "
            "WHEN MATCHED THEN UPDATE SET BODY = %s "
            "WHEN NOT MATCHED THEN INSERT (NOTE_ID, PATIENT_ID, ENCOUNTER_ID, NOTE_TYPE, TITLE, NOTE_DATE, AUTHOR, BODY, CONTAINS_INJECTION) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'Duty clinician', %s, FALSE)",
            (note_id, body, note_id, patient_id, enc_id, note_type, title, day, body),
        )
    print(f"generated {len(rows)} notes")
    conn.close()


if __name__ == "__main__":
    main()
