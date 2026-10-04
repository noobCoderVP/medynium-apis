"""Pure helpers for report upload and review: the file type from its bytes, a safe filename, UTC times and the checks on an
edited row. No I/O, so each is tested directly."""

import datetime as dt
import math
import re
from pathlib import Path
from typing import Any

from medynium_api.core.errors import invalid
from medynium_api.core.snowflake.queries import Row, json_value
from medynium_api.features.reports.extraction import IST, LAB_NAMES, squash
from medynium_api.features.reports.schemas import RowEdit

SUPPORTED_TESTS = set(LAB_NAMES.values())
MAGIC = (
    (b"%PDF-", "application/pdf", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
)


def sniff(data: bytes) -> tuple[str, str] | None:
    """The file type from its own first bytes. A name or a declared type is never trusted."""
    return next(((mime, ext) for magic, mime, ext in MAGIC if data.startswith(magic)), None)


def clean_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._() -]", "_", Path(name).name)[:120].strip() or "report"


def to_utc(value: dt.datetime) -> dt.datetime:
    aware = (
        value if value.tzinfo else value.replace(tzinfo=IST)
    )  # a time typed without a zone is the clinician's IST
    return aware.astimezone(dt.UTC).replace(tzinfo=None, microsecond=0)


def checked_edit(row: Row, body: RowEdit) -> tuple[dict[str, Any], str | None, bool, list[str]]:
    kind, fields = row["kind"], dict(body.fields)
    flags = [f for f in (json_value(row["flags"]) or []) if f not in ("unmatched_test", "no_date")]
    when: str | None = None
    if kind == "LAB":
        value = fields.get("value_num")
        if fields.get("loinc_code") not in SUPPORTED_TESTS:
            raise invalid(
                "Pick one of the supported tests.",
                [{"field": "loinc_code", "problem": "unsupported"}],
            )
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or not 0 <= value <= 1_000_000
        ):
            raise invalid(
                "The value is not plausible.",
                [{"field": "value_num", "problem": "not plausible"}],
            )
        if body.collected_at is None:
            raise invalid(
                "A lab result needs the time it was collected.",
                [{"field": "collected_at", "problem": "required"}],
            )
        instant = to_utc(body.collected_at)
        if instant > dt.datetime.now(dt.UTC).replace(tzinfo=None) + dt.timedelta(minutes=5):
            raise invalid(
                "The collection time cannot be in the future.",
                [{"field": "collected_at", "problem": "future"}],
            )
        fields = {k: fields.get(k) for k in ("test", "loinc_code", "value_num", "unit")}
        when = instant.isoformat(sep=" ")
    elif kind == "MEDICATION":
        name = str(fields.get("description") or "").strip()
        if not 2 <= len(name) <= 120:
            raise invalid(
                "Enter the medicine's name.", [{"field": "description", "problem": "required"}]
            )
        fields = {
            k: (str(fields[k]).strip() or None) if fields.get(k) is not None else None
            for k in ("description", "strength_text", "dose_text", "start_date", "stop_date")
        }
    else:
        name = str(fields.get("description") or "").strip()
        if not name:
            raise invalid("Enter the diagnosis.", [{"field": "description", "problem": "required"}])
        fields = {"description": name[:200], "onset_date": fields.get("onset_date") or None}
    for key in ("start_date", "stop_date", "onset_date"):
        if fields.get(key):
            try:
                dt.date.fromisoformat(str(fields[key]))
            except ValueError:
                raise invalid(
                    "Dates are written year-month-day.", [{"field": key, "problem": "format"}]
                ) from None
    return fields, when, when is not None, flags


def already_in_record(
    waiting: list[Row], labs: list[Row], listed: list[str]
) -> dict[str, list[str]]:
    """Rows still waiting that the record already holds: the same test on the same day with the same value (`duplicate`), or a
    medicine already on the active list (`already_listed`). Shown so a doctor does not approve a second copy."""
    have = {(r["loinc_code"], r["d"], float(r["value_num"] or 0)) for r in labs}
    out: dict[str, list[str]] = {r["row_id"]: [] for r in waiting}
    for r in waiting:
        f = json_value(r["fields"]) or {}
        if r["kind"] == "LAB" and r["collected_at"]:
            day = r["collected_at"].replace(tzinfo=dt.UTC).astimezone(IST).date()
            if (f.get("loinc_code"), day, float(f.get("value_num") or 0)) in have:
                out[r["row_id"]].append("duplicate")
        if r["kind"] == "MEDICATION":
            name = squash(f.get("description", ""))
            if name and any(name.startswith(m) or m.startswith(name) for m in listed):
                out[r["row_id"]].append("already_listed")
    return out
