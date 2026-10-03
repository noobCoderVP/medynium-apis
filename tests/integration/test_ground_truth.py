"""Every number the product shows equals its ground-truth SQL (Q-1, 07 section 2).

The SQL lives in tests/ground_truth/. It runs under the signed-in user's own role, so the row access policy scopes
it exactly as it scopes the app. Nothing here compares against a hand-typed expected value.
"""

from pathlib import Path
from typing import Any

import pytest

from medynium_api.core.snowflake.queries import fetch_all
from medynium_api.core.snowflake.role_session import user_cursor
from tests.integration.test_dashboard import signed_in

GROUND_TRUTH = Path(__file__).resolve().parents[1] / "ground_truth"
S1 = "P-1042"

# Each number the UI shows, and the file that proves it. Add a row here when a new number appears on screen.
SHOWN_NUMBERS = {
    "dashboard utilization.patients (doctor)": "worklist_size.sql",
    "dashboard utilization.patients (assistant)": "worklist_size.sql",
    "patient overview utilisation counts": "s1_utilization.sql",
    "patient overview billed and approved": "s1_utilization.sql",
    "claims tab utilisation and totals": "s1_utilization.sql",
    "latest and previous eGFR": "s1_egfr.sql",
    "current medicines": "s1_active_medications.sql",
}


def test_every_shown_number_has_a_ground_truth_file() -> None:
    missing = [
        f"{number}: {name}"
        for number, name in SHOWN_NUMBERS.items()
        if not (GROUND_TRUTH / name).read_text(encoding="utf-8").strip()
    ]
    assert not missing, f"no ground truth for: {missing}"


def test_no_ground_truth_file_is_orphaned() -> None:
    used = set(SHOWN_NUMBERS.values())
    assert {p.name for p in GROUND_TRUTH.glob("*.sql")} == used


def truth(role: str, name: str, as_of: str = "2026-10-02") -> list[dict[str, Any]]:
    sql = (GROUND_TRUTH / name).read_text(encoding="utf-8").replace("{{AS_OF}}", as_of)
    with user_cursor(role) as cur:
        return fetch_all(cur, sql.strip().rstrip(";"))


live = pytest.mark.snowflake


@live
def test_worklist_size_per_user_equals_ground_truth(users: dict) -> None:
    for key in ("sharma", "assistant", "second"):
        email = {
            "sharma": "sharma@demo.medynium",
            "assistant": "assistant@demo.medynium",
            "second": "second.doctor@demo.medynium",
        }[key]
        shown = signed_in(email).get("/dashboard").json()["utilization"]["patients"]
        assert shown == truth(users[key]["snowflake_role"], "worklist_size.sql")[0]["n"], key


@live
def test_s1_utilisation_equals_ground_truth_on_overview_and_claims(users: dict) -> None:
    client = signed_in("sharma@demo.medynium")
    as_of = client.get("/dashboard").json()["as_of"]
    expected = truth(users["sharma"]["snowflake_role"], "s1_utilization.sql", as_of)[0]
    overview = client.get(f"/patients/{S1}").json()["utilization"]
    claims = client.get(f"/patients/{S1}/claims").json()["utilization"]
    for shown in (overview, claims):
        assert shown["opd_visits"] == expected["opd_visits"]
        assert shown["emergency_visits"] == expected["emergency_visits"]
        assert shown["hospitalizations"] == expected["hospitalizations"]
        assert shown["procedures"] == expected["procedures"]
        assert shown["billed"]["amount"] == pytest.approx(float(expected["billed_inr"]), abs=0.01)
        assert shown["approved"]["amount"] == pytest.approx(
            float(expected["approved_inr"]), abs=0.01
        )


@live
def test_s1_latest_and_previous_egfr_equal_ground_truth(users: dict) -> None:
    rows = truth(users["sharma"]["snowflake_role"], "s1_egfr.sql")
    labs = signed_in("sharma@demo.medynium").get(f"/patients/{S1}").json()["latest_labs"]
    egfr = next(lab for lab in labs if lab["test"] == "eGFR")
    assert egfr["value"] == pytest.approx(float(rows[0]["value_num"]))
    assert egfr["date"] == str(rows[0]["observed_on"])
    assert egfr["previous"]["value"] == pytest.approx(float(rows[1]["value_num"]))
    assert egfr["previous"]["date"] == str(rows[1]["observed_on"])


@live
def test_s1_current_medicines_equal_ground_truth(users: dict) -> None:
    expected = {
        r["drug_name"]
        for r in truth(users["sharma"]["snowflake_role"], "s1_active_medications.sql")
    }
    client = signed_in("sharma@demo.medynium")
    listed = {m["drug"] for m in client.get(f"/patients/{S1}/medications").json()["items"]}
    overview = {m["drug"] for m in client.get(f"/patients/{S1}").json()["medications"]}
    assert listed == overview == expected
