"""Lease a connection as the service role, or as one app user's role U_<id> (ADR-003, SEC-02, SEC-03).

The role name comes from the verified token and is validated against ^U_[0-9A-F]{32}$ before it reaches SQL.
`USE SECONDARY ROLES NONE` stops a previous request's roles leaking in; the role is reset before the
connection goes back to the pool, and if the reset fails the connection is discarded.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import snowflake.connector

from medynium_api.core.config import get_settings
from medynium_api.core.ids import USER_ROLE_PATTERN
from medynium_api.core.snowflake.connection import get_pool


@contextmanager
def service_cursor() -> Iterator[Any]:
    """A cursor under the service role (auth tables only; it has no privilege on patient data)."""
    with get_pool().lease() as conn:
        yield conn.cursor(snowflake.connector.DictCursor)


@contextmanager
def user_cursor(snowflake_role: str) -> Iterator[Any]:
    """A cursor whose active role is the caller's own U_<id> role."""
    if not USER_ROLE_PATTERN.match(snowflake_role):
        raise ValueError("invalid role")
    service_role = get_settings().snowflake_api_role
    with get_pool().lease() as conn:
        cur = conn.cursor(snowflake.connector.DictCursor)
        cur.execute("USE SECONDARY ROLES NONE")
        cur.execute(f"USE ROLE {snowflake_role}")
        try:
            yield cur
        finally:
            cur.execute(f"USE ROLE {service_role}")
