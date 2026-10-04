"""Deterministic rules over rows already read from the read models. No SQL, no model: the same rows always give the
same items, so every number can be checked against the record (ground truth) and none of it is invented."""

import datetime as dt
from typing import Any

from medynium_api.core.intel.models import (
    TAB,
    AttentionItem,
    Category,
    ChangeItem,
    ChangeSet,
    GapItem,
    Severity,
    SourceRef,
    SourceType,
)

Row = dict[str, Any]
RANK: dict[str, int] = {"high": 0, "moderate": 1, "info": 2}
MOVEMENT_PCT = (
    20.0  # an in-range result that moved this much since the previous one is worth a line
)
MAX_ATTENTION = 8
EVENT_CATEGORY: dict[str, Category] = {
    "MEDICATION_START": "MEDICATION", "MEDICATION_CHANGE": "MEDICATION", "DIAGNOSIS": "DIAGNOSIS",
    "ENCOUNTER": "VISIT", "NOTE": "NOTE",
}  # fmt: skip
EVENT_SOURCE: dict[str, SourceType] = {
    "MEDICATION_START": "medication", "MEDICATION_CHANGE": "medication", "DIAGNOSIS": "diagnosis",
    "ENCOUNTER": "encounter", "NOTE": "note",
}  # fmt: skip
# Medicines (by name fragment) and the results usually followed alongside them: (names, alternative tests, max age days).
MONITORING: list[tuple[tuple[str, ...], tuple[str, ...], int]] = [
    (("metformin",), ("HbA1c",), 180),
    (("metformin",), ("eGFR", "Creatinine"), 365),
    (("lisinopril", "enalapril", "ramipril", "losartan", "telmisartan"), ("Potassium",), 180),
    (("lisinopril", "enalapril", "ramipril", "losartan", "telmisartan"), ("eGFR", "Creatinine"), 365),
    (("atorvastatin", "rosuvastatin", "simvastatin"), ("LDL",), 365),
    (("levothyroxine",), ("TSH",), 365),
    (("furosemide", "spironolactone"), ("Potassium",), 180),
]  # fmt: skip
DIAGNOSIS_MONITORING: list[tuple[str, tuple[str, ...], int]] = [
    ("diabet", ("HbA1c",), 180),
    ("kidney", ("eGFR", "Creatinine"), 180),
]  # fmt: skip


def num(value: Any) -> float:
    return float(value)


def fmt(value: Any) -> str:
    return f"{num(value):g}"


def day(value: Any) -> dt.date | None:
    if value is None:
        return None
    return value.date() if isinstance(value, dt.datetime) else value


def when(value: dt.date | None) -> str:
    return f"{value.day} {value:%b %Y}" if value else "undated"


def lab_ref(row: Row) -> SourceRef:
    return SourceRef(
        type="lab",
        id=row.get("latest_lab_id"),
        tab=TAB["lab"],
        query={"lab": str(row["short_name"])},
    )


def lab_text(row: Row) -> str:
    return f"{row['short_name']} {fmt(row['latest_value'])}" + (
        f" {row['unit']}" if row.get("unit") else ""
    )


def movement(row: Row) -> tuple[float | None, str | None]:
    """Percent change since the previous result, and the sentence for it."""
    previous = row.get("previous_value")
    if previous is None or num(previous) == 0:
        return None, None
    pct = (num(row["latest_value"]) - num(previous)) / abs(num(previous)) * 100
    then = f"{fmt(previous)} on {when(day(row.get('previous_at')))}"
    if round(pct) == 0:
        return pct, f"Unchanged from {then}"
    return pct, f"{'Up' if pct > 0 else 'Down'} from {then} ({pct:+.0f}%)"


def attention(
    head: Row, labs: list[Row], events: list[Row], pending: list[Row], as_of: dt.date
) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    for lab in labs:
        pct, sentence = movement(lab)
        flagged = lab.get("abnormal_flag") in ("LOW", "HIGH")
        new = bool(lab.get("is_new_since_last_visit"))
        if flagged:
            severity: Severity = "high" if new else "moderate"
            title = f"{lab_text(lab)} ({str(lab['abnormal_flag']).lower()})"
            items.append(AttentionItem(severity=severity, kind="abnormal_lab", title=title, detail=sentence, date=day(lab["latest_at"]), source=lab_ref(lab)))  # fmt: skip
        elif new and pct is not None and abs(pct) >= MOVEMENT_PCT:
            title = f"{lab['short_name']} {'up' if pct > 0 else 'down'} {abs(pct):.0f}%"
            detail = f"{fmt(lab['previous_value'])} to {fmt(lab['latest_value'])}{' ' + lab['unit'] if lab.get('unit') else ''}; still within range"  # fmt: skip
            items.append(AttentionItem(severity="info", kind="lab_movement", title=title, detail=detail, date=day(lab["latest_at"]), source=lab_ref(lab)))  # fmt: skip
    for event in events:
        kind = event["event_type"]
        if kind not in ("MEDICATION_START", "MEDICATION_CHANGE", "DIAGNOSIS"):
            continue
        label = {"MEDICATION_START": "New medicine", "MEDICATION_CHANGE": "Medicine changed", "DIAGNOSIS": "New diagnosis"}[kind]  # fmt: skip
        source = SourceRef(
            type=EVENT_SOURCE[kind], id=event.get("record_id"), tab=TAB[EVENT_SOURCE[kind]]
        )
        items.append(AttentionItem(severity="moderate", kind=kind.lower(), title=f"{label}: {event['title']}", detail=event.get("summary"), date=event["event_date"], source=source))  # fmt: skip
    if head.get("has_recent_emergency") and head.get("last_encounter_kind") == "EMERGENCY":
        source = SourceRef(type="encounter", id=head.get("last_encounter_id"), tab=TAB["encounter"])
        items.append(AttentionItem(severity="high", kind="emergency_visit", title=f"Emergency visit on {when(head['last_encounter_date'])}", detail=head.get("last_encounter_label"), date=head["last_encounter_date"], source=source))  # fmt: skip
    for p in pending:
        k = p["kind"]
        if k in ("ABNORMAL_LAB", "RECENT_EMERGENCY"):  # already covered above, from the same data
            continue
        due = p.get("due_date")
        overdue = k == "FOLLOW_UP" and due is not None and due <= as_of
        sev: Severity = "high" if k == "ESCALATED_FINDING" or overdue else "moderate"
        stype: SourceType = "report" if k == "REPORT_TO_REVIEW" else "finding"
        note = (
            p.get("detail")
            if not due
            else f"{p.get('detail')}; due {when(due)}{' (overdue)' if overdue else ''}"
        )
        items.append(AttentionItem(severity=sev, kind=k.lower(), title=p["title"], detail=note, date=day(p.get("raised_at")), source=SourceRef(type=stype, id=p.get("source_id"), tab=TAB[stype])))  # fmt: skip
    items.sort(key=lambda i: (RANK[i.severity], -(i.date.toordinal() if i.date else 0)))
    return items[:MAX_ATTENTION]


def resolve_since(
    choice: str, previous_visit: dt.date | None, as_of: dt.date
) -> tuple[dt.date, str] | None:
    """The date a change comparison starts from, and how to say it. None when the choice is not understood."""
    if choice == "previous_visit":
        if previous_visit:
            return previous_visit, f"since the previous visit on {when(previous_visit)}"
        return as_of - dt.timedelta(days=90), "in the last 90 days (no previous visit on record)"
    if choice == "90d":
        return as_of - dt.timedelta(days=90), "in the last 90 days"
    if choice == "1y":
        return as_of - dt.timedelta(days=365), "in the last year"
    try:
        start = dt.date.fromisoformat(choice)
    except ValueError:
        return None
    return start, f"since {when(start)}"


def changes(
    since: dt.date, label: str, labs: list[Row], events: list[Row], reports: list[Row]
) -> ChangeSet:
    items: list[ChangeItem] = []
    for lab in labs:
        latest = day(lab["latest_at"])
        if latest is None or latest <= since:
            continue
        pct, sentence = movement(lab)
        flag = (
            f" ({str(lab['abnormal_flag']).lower()})"
            if lab.get("abnormal_flag") in ("LOW", "HIGH")
            else ""
        )
        has_prev = lab.get("previous_value") is not None
        title = (f"{lab['short_name']} {fmt(lab['previous_value'])} to {fmt(lab['latest_value'])}" if has_prev else f"{lab['short_name']} {fmt(lab['latest_value'])} (new result)") + (f" {lab['unit']}" if lab.get("unit") else "") + flag  # fmt: skip
        direction = None if pct is None else ("up" if pct > 0 else "down" if pct < 0 else "same")
        items.append(ChangeItem(category="LAB", title=title, detail=sentence, date=latest, direction=direction, source=lab_ref(lab)))  # fmt: skip
    for event in events:
        category = EVENT_CATEGORY.get(event["event_type"])
        if category is None:  # lab panels are shown per test above; claims are not clinical changes
            continue
        stype = EVENT_SOURCE[event["event_type"]]
        items.append(ChangeItem(category=category, title=event["title"], detail=event.get("summary"), date=event["event_date"], source=SourceRef(type=stype, id=event.get("record_id"), tab=TAB[stype])))  # fmt: skip
    for report in reports:
        items.append(ChangeItem(category="DOCUMENT", title=f"Report: {report['filename']}", detail=f"{report.get('rows_kept') or 0} items read from it", date=day(report["extracted_at"]), source=SourceRef(type="report", id=report["report_id"], tab=TAB["report"])))  # fmt: skip
    items.sort(key=lambda i: (-(i.date.toordinal() if i.date else 0), i.category))
    counts: dict[str, int] = {}
    for item in items:
        counts[item.category] = counts.get(item.category, 0) + 1
    return ChangeSet(since=since, label=label, counts=counts, items=items)


def _latest_of(labs: list[Row], tests: tuple[str, ...]) -> Row | None:
    wanted = {t.lower() for t in tests}
    found = [lab for lab in labs if str(lab["short_name"]).lower() in wanted]
    return max(found, key=lambda lab: lab["latest_at"], default=None)


def gaps(
    meds: list[Row], labs: list[Row], diagnoses: list[str], allergy_count: int, as_of: dt.date
) -> list[GapItem]:
    out: list[GapItem] = []
    seen: set[tuple[str, ...]] = set()

    def check(
        subject: str, tests: tuple[str, ...], max_days: int, source: SourceRef | None
    ) -> None:
        if tests in seen:
            return
        row = _latest_of(labs, tests)
        latest = day(row["latest_at"]) if row else None
        if latest is not None and (as_of - latest).days <= max_days:
            return
        seen.add(tests)
        months = round(max_days / 30)
        last = f"latest {when(latest)}" if latest else "none on record"
        out.append(GapItem(kind="monitoring", title=f"{tests[0]} not seen in the last {months} months", detail=f"{subject}; {last}. This is a usual follow-up check, not a rule for this patient.", source=source))  # fmt: skip

    for names, tests, max_days in MONITORING:
        for med in meds:
            if any(
                n in str(med.get("drug_name") or med.get("description") or "").lower()
                for n in names
            ):
                source = SourceRef(
                    type="medication", id=med.get("medication_id"), tab=TAB["medication"]
                )
                check(f"{med.get('drug_name')} is an active medicine", tests, max_days, source)
                break
    for fragment, tests, max_days in DIAGNOSIS_MONITORING:
        match = next((d for d in diagnoses if fragment in d.lower()), None)
        if match:
            check(
                f"{match} is an active diagnosis",
                tests,
                max_days,
                SourceRef(type="diagnosis", tab=TAB["diagnosis"]),
            )
    for med in meds:
        if not med.get("drug_id"):
            out.append(GapItem(kind="label_not_indexed", title=f"No indexed label for {med.get('drug_name') or med.get('description')}", detail="The safety review cannot check this medicine against label text.", source=SourceRef(type="medication", id=med.get("medication_id"), tab=TAB["medication"])))  # fmt: skip
    if allergy_count == 0:
        out.append(GapItem(kind="allergy_unknown", title="No allergy information recorded", detail="Neither an allergy nor 'no known allergies' is on the record."))  # fmt: skip
    return out
