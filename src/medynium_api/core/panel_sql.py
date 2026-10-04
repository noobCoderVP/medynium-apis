"""SQL shared by the Pending page (features/pending) and the assistant's panel tools (features/copilot), so a person
and the assistant ask the database the same question and get the same rows (manual parity, AI-10).

Everything here reads read models and the pending view under the caller's own role: the row access policies decide
which patients appear. Nothing here is built from request text except bound values."""

PENDING_COLUMNS = "ITEM_ID, PATIENT_ID, PATIENT_NAME, KIND, TITLE, DETAIL, DUE_DATE, RAISED_AT, SOURCE_TABLE, SOURCE_ID"
PENDING_ORDER = "PRIORITY, DUE_DATE NULLS LAST, RAISED_AT DESC, ITEM_ID"
PENDING_KINDS = (
    "ESCALATED_FINDING", "FOLLOW_UP", "OPEN_FINDING", "REPORT_TO_REVIEW", "ABNORMAL_LAB", "RECENT_EMERGENCY",
)  # fmt: skip

WORKLIST_COLUMNS = (
    "PATIENT_ID, FULL_NAME, AGE_YEARS, SEX, MAIN_DIAGNOSES, LAST_ENCOUNTER_DATE, LAST_ENCOUNTER_KIND, "
    "LAST_ENCOUNTER_LABEL, NEW_LAB_COUNT, HAS_NEW_LAB, HAS_NEW_MEDICATION_CHANGE, HAS_RECENT_EMERGENCY, "
    "HAS_NEW_DOCUMENT, FLAG_COUNT"
)
# Urgent first (as ranked in core/ranking.py), then most recently changed.
WORKLIST_ORDER = (
    "HAS_RECENT_EMERGENCY DESC, FLAG_COUNT DESC, LAST_CHANGE_DATE DESC NULLS LAST, PATIENT_ID"
)


def pending_query(
    kinds: list[str] | None, patient_id: str | None, *, count: bool = False
) -> tuple[str, list[object]]:
    """The pending list (or its count), optionally narrowed to some kinds and one patient. Kinds are checked against
    PENDING_KINDS, so only fixed words reach the SQL; the patient id is bound."""
    where: list[str] = ["TRUE"]
    params: list[object] = []
    wanted = [k for k in (kinds or []) if k in PENDING_KINDS]
    if wanted:
        where.append(f"KIND IN ({', '.join(['%s'] * len(wanted))})")
        params += wanted
    if patient_id:
        where.append("PATIENT_ID = %s")
        params.append(patient_id)
    clause = " AND ".join(where)
    if count:
        return (
            f"SELECT KIND, COUNT(*) AS N FROM ANALYTICS.PENDING_ITEM WHERE {clause} GROUP BY KIND",
            params,
        )
    return (
        f"SELECT {PENDING_COLUMNS}, COUNT(*) OVER () AS TOTAL FROM ANALYTICS.PENDING_ITEM WHERE {clause} "
        f"ORDER BY {PENDING_ORDER} LIMIT %s OFFSET %s",
        params,
    )
