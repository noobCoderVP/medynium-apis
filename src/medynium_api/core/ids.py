"""Identifier helpers. Readable prefixes; uniqueness comes from random hex."""

import re
import secrets
import uuid

USER_ROLE_PATTERN = re.compile(r"^U_[0-9A-F]{32}$")


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_id(prefix: str, length: int = 8) -> str:
    return f"{prefix}-{secrets.token_hex(length // 2 + length % 2)[:length].upper()}"


def request_id() -> str:
    return secrets.token_hex(6)


def role_for_user(user_id: str) -> str:
    """The Snowflake role name for an app user id. Validated before it is ever used in SQL."""
    role = "U_" + user_id.replace("-", "").upper()
    if not USER_ROLE_PATTERN.match(role):
        raise ValueError("invalid user id")
    return role
