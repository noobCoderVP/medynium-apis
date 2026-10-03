"""The access chain at the SQL level (G4, SEC-02, SEC-03): per-user roles drive the row access policies."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from medynium_api.core.snowflake.queries import fetch_all
from medynium_api.core.snowflake.role_session import service_cursor, user_cursor

pytestmark = pytest.mark.snowflake
S3 = "P-1093"
S1 = "P-1042"


def patient_ids(role: str, table: str = "CLINICAL.PATIENT") -> set[str]:
    with user_cursor(role) as cur:
        return {r["patient_id"] for r in fetch_all(cur, f"SELECT PATIENT_ID FROM {table}")}


def test_service_role_alone_cannot_read_patient_data() -> None:
    with (
        service_cursor() as cur,
        pytest.raises(Exception, match="does not exist or not authorized"),
    ):
        cur.execute("SELECT COUNT(*) FROM CLINICAL.PATIENT")


def test_assistant_sees_nothing_of_s3_in_any_table(users: dict) -> None:
    role = users["assistant"]["snowflake_role"]
    for table in ("CLINICAL.PATIENT", "CLINICAL.MEDICATION", "CLINICAL.LAB_RESULT", "ANALYTICS.PATIENT_360",
                  "ANALYTICS.DASHBOARD_WORKLIST", "ANALYTICS.PATIENT_TIMELINE", "CLINICAL.CLINICAL_NOTE"):  # fmt: skip
        assert S3 not in patient_ids(role, table), table
    assert S1 in patient_ids(role)


def test_doctor_sees_s3(users: dict) -> None:
    assert S3 in patient_ids(users["sharma"]["snowflake_role"], "ANALYTICS.PATIENT_360")


def test_doctors_are_isolated_from_each_other(users: dict) -> None:
    sharma = patient_ids(users["sharma"]["snowflake_role"])
    second = patient_ids(users["second"]["snowflake_role"])
    assert sharma and second
    assert sharma.isdisjoint(second)


def test_assistant_is_a_subset_of_the_supervising_doctor(users: dict) -> None:
    assert patient_ids(users["assistant"]["snowflake_role"]) < patient_ids(
        users["sharma"]["snowflake_role"]
    )


def test_role_switch_leaks_nothing_between_requests(users: dict) -> None:
    for _ in range(10):
        assert S3 in patient_ids(users["sharma"]["snowflake_role"])
        assert S3 not in patient_ids(users["assistant"]["snowflake_role"])


def test_no_role_leakage_under_concurrent_load(users: dict) -> None:
    """Q-A5: 200 alternating requests from two roles at once. Pooled connections are reused across roles, so a
    role that failed to reset would show up here as the assistant seeing S3, or the doctor losing it."""
    doctor, assistant = users["sharma"]["snowflake_role"], users["assistant"]["snowflake_role"]

    def one(i: int) -> tuple[str, bool]:
        role = doctor if i % 2 == 0 else assistant
        return ("doctor" if i % 2 == 0 else "assistant", S3 in patient_ids(role))

    with ThreadPoolExecutor(max_workers=8) as pool:
        seen = list(pool.map(one, range(200)))
    assert all(sees_s3 for who, sees_s3 in seen if who == "doctor")
    assert not any(sees_s3 for who, sees_s3 in seen if who == "assistant")


def test_an_unknown_role_is_refused() -> None:
    with pytest.raises(ValueError), user_cursor("MED_ADMIN"):
        pass
    with pytest.raises(ValueError), user_cursor("U_1;DROP TABLE X"):
        pass
