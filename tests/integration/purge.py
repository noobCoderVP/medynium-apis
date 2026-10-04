"""Test clean-up: remove the patients a live test created, and everything hanging off them.

The API only ever archives (nothing is deleted at run time), so tests that register patients delete them here as the
setup role, the same role that loads the data. Test patients are recognised by the name prefix "Zz Test", so a real
patient can never be matched."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from sfadmin import connect

PREFIX = "Zz Test"
TABLES = (
    "CLINICAL.REPORT_ROW",
    "CLINICAL.REPORT_PAGE",
    "CLINICAL.REPORT",
    "CLINICAL.ALLERGY",
    "CLINICAL.CLINICAL_NOTE",
    "CLINICAL.LAB_RESULT",
    "CLINICAL.MEDICATION",
    "CLINICAL.DIAGNOSIS",
    "CLINICAL.ENCOUNTER",
    "CLINICAL.RECORD_HISTORY",
    "SECURITY.PATIENT_ENTITLEMENT",
    "ANALYTICS.DASHBOARD_WORKLIST",
    "ANALYTICS.UTILIZATION",
    "ANALYTICS.PATIENT_TIMELINE",
    "ANALYTICS.PATIENT_LAB_LATEST",
    "ANALYTICS.CURRENT_MEDICATIONS",
    "ANALYTICS.PATIENT_360",
    "ANALYTICS.FINDING",
    "CLINICAL.PATIENT",
)


def purge_test_patients() -> list[str]:
    conn = connect("MED_ADMIN", "MEDYNIUM")
    try:
        cur = conn.cursor()
        cur.execute("USE WAREHOUSE MEDYNIUM_WH")
        cur.execute(
            "SELECT PATIENT_ID FROM CLINICAL.PATIENT WHERE FULL_NAME LIKE %s", (f"{PREFIX}%",)
        )
        ids = [r[0] for r in cur.fetchall()]
        for patient_id in ids:
            for table in TABLES:
                cur.execute(f"DELETE FROM {table} WHERE PATIENT_ID = %s", (patient_id,))
        for patient_id in ids:  # the uploaded files go too
            cur.execute(f"REMOVE @INTAKE.REPORT_STAGE/{patient_id}/")
        cur.execute("DELETE FROM INTAKE.REQUEST_LOG WHERE REQUEST_KEY LIKE 'test-%'")
        return ids
    finally:
        conn.close()


def clear_lab_reviews(lab_ids: list[str]) -> None:
    """Remove the "reviewed" marks a test made, so the seeded dataset keeps its pending items."""
    if not lab_ids:
        return
    conn = connect("MED_ADMIN", "MEDYNIUM")
    try:
        cur = conn.cursor()
        cur.execute("USE WAREHOUSE MEDYNIUM_WH")
        marks = ", ".join(["%s"] * len(lab_ids))
        cur.execute(f"DELETE FROM ANALYTICS.LAB_REVIEW WHERE LAB_ID IN ({marks})", lab_ids)
    finally:
        conn.close()


def entitle(user_id: str, snowflake_role: str, patient_id: str) -> None:
    """Give a user a test patient (an assistant's entitlements are an admin's to set, so a test does it as setup does)."""
    conn = connect("MED_ADMIN", "MEDYNIUM")
    try:
        cur = conn.cursor()
        cur.execute("USE WAREHOUSE MEDYNIUM_WH")
        cur.execute(
            "INSERT INTO SECURITY.PATIENT_ENTITLEMENT (ENTITLEMENT_ID, PATIENT_ID, USER_ID, SNOWFLAKE_ROLE, GRANTED_BY, GRANTED_AT) "
            "SELECT UUID_STRING(), %s, %s, %s, %s, SYSDATE()",
            (patient_id, user_id, snowflake_role, user_id),
        )
    finally:
        conn.close()


def clear_drug_requests() -> None:
    """Remove the drug requests tests made (their text starts "Zz test")."""
    conn = connect("MED_ADMIN", "MEDYNIUM")
    try:
        cur = conn.cursor()
        cur.execute("USE WAREHOUSE MEDYNIUM_WH")
        cur.execute("DELETE FROM SECURITY.DRUG_REQUEST WHERE DRUG_TEXT LIKE 'Zz test%'")
    finally:
        conn.close()
