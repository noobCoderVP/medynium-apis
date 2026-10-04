"""Refreshing one patient gives exactly the rows the bulk build gave (production plan P1.2).

The two paths hold the same logic in two SQL files (30_build_analytics.sql and 35_refresh_patient.sql). This test is what
stops them drifting: it takes each patient's rows from the last bulk build, refreshes that one patient and compares."""

import pytest

from tests.integration.purge import connect

pytestmark = pytest.mark.snowflake
AS_OF = "2026-10-02"  # the date the seeded dataset was last bulk-built for
PATIENTS = ["P-1042", "P-1067", "P-1093", "P-1101", "P-1118", "P-1126", "P-1133"]
TABLES = [
    "PATIENT_360", "CURRENT_MEDICATIONS", "PATIENT_LAB_LATEST", "PATIENT_TIMELINE", "UTILIZATION",
    "DASHBOARD_WORKLIST",
]  # fmt: skip


def rows(cur: object, table: str, patient_id: str) -> list[tuple]:
    cur.execute(
        f"SELECT * FROM ANALYTICS.{table} WHERE PATIENT_ID = %s ORDER BY 1, 2, 3, 4", (patient_id,)
    )  # type: ignore[attr-defined]
    return [tuple(str(v) for v in r) for r in cur.fetchall()]  # type: ignore[attr-defined]


@pytest.mark.parametrize("patient_id", PATIENTS)
def test_one_patient_refresh_equals_the_bulk_build(users: dict, patient_id: str) -> None:
    conn = connect("MED_ADMIN", "MEDYNIUM")
    try:
        cur = conn.cursor()
        cur.execute("USE WAREHOUSE MEDYNIUM_WH")
        before = {t: rows(cur, t, patient_id) for t in TABLES}
        assert before["PATIENT_360"], "the patient must have been built by the bulk script"
        cur.execute("CALL INTAKE.REFRESH_PATIENT(%s, %s::DATE, FALSE)", (patient_id, AS_OF))
        assert cur.fetchone()[0] == "refreshed"
        after = {t: rows(cur, t, patient_id) for t in TABLES}
        for table in TABLES:
            assert after[table] == before[table], f"{table} differs for {patient_id}"
    finally:
        conn.close()
