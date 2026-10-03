"""The patient-list filter object and the sort keys each list accepts (no SQL here, no imports of Snowflake)."""

from dataclasses import dataclass

from medynium_api.core.ranking import score_sql


@dataclass(frozen=True)
class PatientFilters:
    q: str | None = None
    changed: bool = False
    sex: str | None = None
    kind: str | None = None
    flag: str | None = None
    sort: str | None = None
    order: str = "desc"


# Sort keys the API accepts -> the column they order by. Nothing else ever reaches the SQL.
PATIENT_SORTS = {
    "name": "w.FULL_NAME",
    "age": "w.AGE_YEARS",
    "last_encounter": "w.LAST_ENCOUNTER_DATE",
    "flags": f"({score_sql('w.')})",
}
FLAG_COLUMNS = {
    "NEW_LAB": "w.NEW_LAB_COUNT > 0",
    "NEW_MEDICATION": "w.HAS_NEW_MEDICATION_CHANGE",
    "RECENT_EMERGENCY": "w.HAS_RECENT_EMERGENCY",
    "NEW_DOCUMENT": "w.HAS_NEW_DOCUMENT",
}
MEDICATION_SORTS = {
    "drug": "COALESCE(m.DRUG_NAME, m.DESCRIPTION)",
    "started": "m.START_DATE",
    "last_change": "m.LAST_CHANGE_DATE",
}
LAB_SORTS = {"test": "SHORT_NAME", "date": "LATEST_AT", "value": "LATEST_VALUE"}
