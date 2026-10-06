"""The written summary of a panel answer and the grouping of pending rows, kept apart from the handler (panel.py).
Everything here is built from the rows and counts the SQL returned; no model writes it and nothing touches the
database. Patient-by-patient statements are only shown when the clinician asks for them (`wants_detail`)."""

import datetime as dt
from typing import Any

from medynium_api.core.snowflake.queries import Row

PLAN_RECORD = (
    "Panel plan"  # the stored evidence row that remembers which tools produced a panel answer
)
SHOWN = 5  # names quoted inside a summary sentence
KIND_LABEL = {
    "ABNORMAL_LAB": "abnormal lab", "REPORT_TO_REVIEW": "report to review",
    "RECENT_EMERGENCY": "recent emergency visit", "FOLLOW_UP": "follow-up",
    "OPEN_FINDING": "open finding", "ESCALATED_FINDING": "escalated finding",
}  # fmt: skip
HINT = " Ask me to list them for the patient-by-patient detail."


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _names(rows: list[Row], key: str, limit: int = SHOWN) -> str:
    seen: list[str] = []
    for r in rows:
        name = str(r[key])
        if name not in seen:
            seen.append(name)
        if len(seen) == limit:
            break
    return ", ".join(seen)


def patients_summary(counts: Row | None, rows: list[Row], total: int, detail: bool) -> str:
    """ "You have 158 patients. 10 need attention (2 with a recent emergency visit, ...). Most urgent: ..."."""
    text = f"You have {_count(total, 'patient')}."
    if counts:
        bits = [
            (int(counts["emergency"] or 0), "with a recent emergency visit"),
            (int(counts["med_changes"] or 0), "with a medication change"),
            (int(counts["new_docs"] or 0), "with a new document"),
        ]
        shown = [f"{n} {label}" for n, label in bits if n]
        needs = int(counts["needs_attention"] or 0)
        text += f" {needs} need attention" + (f" ({', '.join(shown)})" if shown else "") + "."
    if rows:
        text += f" Most urgent: {_names(rows, 'full_name', 3)}."
    return text + ("" if detail or not rows else HINT)


def matching_summary(total: int, described: str, rows: list[Row], limit: int, detail: bool) -> str:
    text = f"{total} of your patients match ({described})"
    text += "." if total <= limit or not detail else f"; the first {limit} are listed."
    if rows:
        text += f" Including {_names(rows, 'full_name')}."
    return text + ("" if detail or not rows else HINT)


def pending_summary(
    counts: list[Row], total: int, overdue: int, rows: list[Row], detail: bool
) -> str:
    if not total:
        return "Nothing is waiting for you."
    parts = [
        _count(
            int(c["n"]), KIND_LABEL.get(str(c["kind"]), str(c["kind"]).lower().replace("_", " "))
        )
        for c in sorted(counts, key=lambda c: -int(c["n"]))
    ]
    text = f"{_count(total, 'item')} {'is' if total == 1 else 'are'} waiting for you"
    text += f": {', '.join(parts)}" if parts else ""
    text += f" ({overdue} overdue)" if overdue else ""
    text += "."
    if rows:
        text += f" Most urgent for: {_names(rows, 'patient_name', 3)}."
    return text + ("" if detail or not rows else HINT)


def group_pending(rows: list[Row]) -> list[dict[str, Any]]:
    """One entry per patient, in the order the SQL ranked them: the patient's items joined into one line."""
    grouped: dict[str, dict[str, Any]] = {}
    for r in rows:
        entry = grouped.setdefault(
            r["patient_id"], {"patient_id": r["patient_id"], "name": r["patient_name"], "rows": []}
        )
        entry["rows"].append(r)
    out = []
    for entry in grouped.values():
        titles = []
        for r in entry["rows"]:
            due: dt.date | None = r["due_date"]
            titles.append(f"{r['title']}, due {due:%d %b}" if due else str(r["title"]))
        extra = len(titles) - 4
        line = (
            f"{entry['name']}: " + "; ".join(titles[:4]) + (f"; +{extra} more" if extra > 0 else "")
        )
        out.append({**entry, "text": line, "first": entry["rows"][0], "many": len(titles) > 1})
    return out
