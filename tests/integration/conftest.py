"""Fixtures for tests that need the live Snowflake account and the seeded demo users."""

import pytest

from medynium_api.core.config import get_settings
from medynium_api.core.snowflake.queries import fetch_all
from medynium_api.core.snowflake.role_session import service_cursor

EMAILS = {
    "sharma": "sharma@demo.medynium",
    "second": "second.doctor@demo.medynium",
    "assistant": "assistant@demo.medynium",
}


@pytest.fixture(scope="session", autouse=True)
def direct_api_cookie_path() -> None:
    """Tests call the API directly, not through the UI's /api proxy, so the refresh cookie lives under /auth."""
    mp = pytest.MonkeyPatch()
    mp.setenv("REFRESH_COOKIE_PATH", "/auth")
    # The ground-truth numbers belong to the seeded dataset as of this date; unset in production means today (IST).
    mp.setenv("DEMO_AS_OF_DATE", "2026-10-02")
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def users() -> dict[str, dict]:
    if not get_settings().snowflake_configured:
        pytest.skip("Snowflake is not configured")
    with service_cursor() as cur:
        rows = fetch_all(
            cur, "SELECT USER_ID, EMAIL, SNOWFLAKE_ROLE, ROLE_CODE FROM SECURITY.APP_USER"
        )
    by_email = {r["email"]: r for r in rows}
    missing = [e for e in EMAILS.values() if e not in by_email]
    if missing:
        pytest.skip(f"demo users not seeded: {missing}")
    return {key: by_email[email] for key, email in EMAILS.items()}
