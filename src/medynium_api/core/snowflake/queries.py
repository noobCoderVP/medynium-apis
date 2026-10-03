"""Parameterised query helpers. Always bind values (%s); identifiers are never built from request data."""

import json
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

Row = dict[str, Any]
Params = Sequence[Any] | dict[str, Any] | None


def _lower(row: dict[str, Any]) -> Row:
    return {key.lower(): value for key, value in row.items()}


def fetch_all(cur: Any, sql: str, params: Params = None) -> list[Row]:
    cur.execute(sql, params)
    return [_lower(row) for row in cur.fetchall()]


def fetch_one(cur: Any, sql: str, params: Params = None) -> Row | None:
    cur.execute(sql, params)
    row = cur.fetchone()
    return _lower(row) if row else None


def execute(cur: Any, sql: str, params: Params = None) -> int:
    cur.execute(sql, params)
    return int(cur.rowcount or 0)


def json_value(value: Any) -> Any:
    """VARIANT columns come back as JSON text; parse them."""
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value


def iso(value: date | datetime | None) -> str | None:
    """ISO text for dates and UTC instants (instants get a trailing Z)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat() + ("Z" if value.tzinfo is None else "")
    return value.isoformat()


def money(value: Any) -> dict[str, Any]:
    return {"amount": float(value or 0), "currency": "INR"}


def explain_sql(sql: str, params: Params = None) -> str:
    """The statement with its values filled in, for the Why? panel and for replay. Display only: never executed."""
    if not params:
        return sql.strip()
    values = list(params.values()) if isinstance(params, dict) else list(params)

    def literal(value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool | int | float):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"

    parts = sql.strip().split("%s")
    out = parts[0]
    for part, value in zip(parts[1:], values, strict=False):
        out += literal(value) + part
    return out
