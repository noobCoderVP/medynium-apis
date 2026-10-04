"""The admin screen's golden-run feed against the live account."""

import pytest

from tests.integration.test_dashboard import signed_in

pytestmark = pytest.mark.snowflake


def test_an_admin_sees_the_stored_run_and_others_are_refused(users: dict) -> None:
    body = signed_in("sharma@demo.medynium").get("/admin/golden-runs")
    assert body.status_code == 200
    latest = body.json()["latest"]
    assert latest is None or (
        latest["total"] == len(latest["cases"]) and latest["passed"] <= latest["total"]
    )
    assert signed_in("assistant@demo.medynium").get("/admin/golden-runs").status_code == 403
