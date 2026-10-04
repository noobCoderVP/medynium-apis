"""Turn a model's reading of a report page into rows a doctor can review. Pure functions, no I/O.

The model proposes; this module decides what survives. A row is kept only when the words it quotes really are on the
page and the number it reports really is in that quote, so a model that invents or misreads a value loses the row
rather than adding a wrong one to a record. Confidence is set here from what could be checked, never taken from the
model. Dates are read day-first, the way Indian reports write them, and a missing time is never guessed."""

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from typing import Any

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
# Names a lab prints for the tests the reference table knows, mapped to their LOINC code (CLINICAL.LAB_REFERENCE).
LAB_NAMES: dict[str, str] = {
    "haemoglobin": "718-7", "hemoglobin": "718-7", "hb": "718-7", "hgb": "718-7",
    "hba1c": "4548-4", "a1c": "4548-4", "glycated haemoglobin": "4548-4", "glycosylated haemoglobin": "4548-4",
    "haemoglobin a1c": "4548-4", "hemoglobin a1c": "4548-4",
    "creatinine": "38483-4", "serum creatinine": "38483-4",
    "egfr": "33914-3", "estimated gfr": "33914-3", "glomerular filtration rate": "33914-3",
    "potassium": "6298-4", "serum potassium": "6298-4", "k+": "6298-4",
    "sodium": "2951-2", "serum sodium": "2951-2", "na+": "2951-2",
    "tsh": "3016-3", "thyroid stimulating hormone": "3016-3", "thyrotropin": "3016-3",
    "ldl": "18262-6", "ldl cholesterol": "18262-6", "ldl-c": "18262-6", "ldl c": "18262-6",
    "glucose": "2339-0", "fasting glucose": "2339-0", "fasting blood sugar": "2339-0", "fbs": "2339-0",
    "blood sugar": "2339-0", "random blood sugar": "2339-0", "rbs": "2339-0",
}  # fmt: skip
# Words on a page that talk to an AI instead of describing a patient. A row quoting them is dropped even though the
# words are on the page, so text planted in a report cannot become a medicine in a record.
INSTRUCTION = re.compile(
    r"ignore (all |any |the )?(previous|prior|above|earlier)|\bsystem prompt\b|\bas an ai\b|\byou (must|should|are now)\b"
    r"|\b(assistant|ai|model|llm)\b.{0,30}\b(must|should|add|run|open|delete|call)\b|\binstruction(s)?\b|\bdisregard\b",
    re.IGNORECASE,
)
TITLES = {"mr", "mrs", "ms", "miss", "dr", "smt", "shri", "sri", "master", "baby", "mx"}
MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}


@dataclass
class Extraction:
    rows: list[dict[str, Any]] = field(default_factory=list)
    dropped: int = 0
    name_on_report: str | None = None
    report_patient_id: str | None = None
    report_collected_at: str | None = None
    injection_seen: bool = False


def squash(text: str) -> str:
    """Text reduced to what must match: case, spacing, and the look-alike quotes and dashes that OCR changes."""
    value = text.lower().replace("–", "-").replace("—", "-").replace("’", "'").replace(" ", " ")
    return re.sub(r"\s+", " ", value).strip()


def numbers_in(text: str) -> list[float]:
    found = []
    for token in re.findall(r"-?\d+(?:[.,]\d+)?", text):
        try:
            found.append(float(token.replace(",", ".")))
        except ValueError:
            continue
    return found


# Dates and times ------------------------------------------------------------------------------------------------
def parse_when(text: str | None) -> tuple[dt.datetime | None, bool]:
    """A printed date (and maybe time) as an instant in UTC, and whether the time was printed. Day first. An
    unreadable value is None, never a guess. A date alone is held at midday IST so its calendar date survives in UTC."""
    if not text:
        return None, False
    raw = squash(text).replace(",", " ")
    t = re.search(r"\b(\d{1,2})[:.](\d{2})(?:[:.]\d{2})?\s*(am|pm)?\b", raw)
    hour = minute = 0
    time_known = False
    rest = raw
    if t:
        hour, minute = int(t.group(1)), int(t.group(2))
        if t.group(3) == "pm" and hour < 12:
            hour += 12
        if t.group(3) == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            return None, False
        time_known = True
        rest = (raw[: t.start()] + " " + raw[t.end() :]).strip()
    day = month = year = None
    iso = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", rest)
    dmy = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", rest)
    named = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3})[a-z]*\.?\s+(\d{2,4})\b", rest)
    named_us = re.search(r"\b([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s+(\d{2,4})\b", rest)
    if iso:
        year, month, day = int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
    elif dmy:
        day, month, year = int(dmy.group(1)), int(dmy.group(2)), int(dmy.group(3))
    elif named and named.group(2) in MONTHS:
        day, month, year = int(named.group(1)), MONTHS[named.group(2)], int(named.group(3))
    elif named_us and named_us.group(1) in MONTHS:
        month, day, year = MONTHS[named_us.group(1)], int(named_us.group(2)), int(named_us.group(3))
    if day is None or month is None or year is None:
        return None, False
    if year < 100:
        year += 2000
    try:
        local = dt.datetime(
            year, month, day, hour if time_known else 12, minute if time_known else 0, tzinfo=IST
        )
    except ValueError:
        return None, False
    if local.date() > dt.datetime.now(IST).date() + dt.timedelta(days=1) or year < 1950:
        return (
            None,
            False,
        )  # a collection date in the future or the distant past is a misreading, not data
    return local.astimezone(dt.UTC).replace(tzinfo=None), time_known


def date_only(text: str | None) -> dt.date | None:
    when, _ = parse_when(text)
    return when.replace(tzinfo=dt.UTC).astimezone(IST).date() if when else None


# Identity -------------------------------------------------------------------------------------------------------
def name_tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", squash(name)) if len(t) > 1 and t not in TITLES}


def identity(
    report_name: str | None, report_id: str | None, patient_name: str, patient_id: str
) -> str:
    """MATCH when the name (or id) on the report is this patient's, MISMATCH when it names someone else, UNKNOWN when
    the report carries no name. Initials and the order of names do not matter."""
    if report_id and report_id.strip().upper() == patient_id.upper():
        return "MATCH"
    if not report_name or not report_name.strip():
        return "UNKNOWN"
    a, b = name_tokens(report_name), name_tokens(patient_name)
    if not a or not b:
        return "UNKNOWN"
    return "MATCH" if len(a & b) / min(len(a), len(b)) >= 0.6 else "MISMATCH"


# Model output ---------------------------------------------------------------------------------------------------
def parse_model_json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("not a JSON object")
    return value


def _text(value: Any, limit: int = 160) -> str | None:
    return (
        str(value).strip()[:limit]
        if value not in (None, "") and not isinstance(value, (dict, list))
        else None
    )


def _confidence(base: float, *, mapped: bool, dated: bool, timed: bool, name_ok: bool) -> float:
    score = (
        base
        + (0.2 if mapped else -0.15)
        + (0.15 if dated else 0.0)
        + (0.1 if timed else 0.0)
        - (0.0 if name_ok else 0.15)
    )
    return round(min(0.99, max(0.05, score)), 3)


def keep_rows(
    page_no: int,
    page_text: str,
    reply: dict[str, Any],
    extraction: Extraction,
    known_drugs: set[str],
) -> None:
    """Check each proposed row against this page and add the survivors. `known_drugs` are normalised names the
    knowledge base can match, used only to flag a medicine that cannot be linked to a label."""
    squashed_page = squash(page_text)
    extraction.name_on_report = extraction.name_on_report or _text(reply.get("patient_name"), 120)
    extraction.report_patient_id = extraction.report_patient_id or _text(
        reply.get("patient_id"), 40
    )
    page_date = _text(reply.get("collected_at"), 60)
    if page_date and squash(page_date) in squashed_page:
        extraction.report_collected_at = extraction.report_collected_at or page_date
    seen: set[tuple[Any, ...]] = {
        (r["kind"], json.dumps(r["fields"], sort_keys=True), r.get("collected_at"))
        for r in extraction.rows
    }
    for item in reply.get("rows") or []:
        if not isinstance(item, dict):
            extraction.dropped += 1
            continue
        quote = _text(item.get("quote"), 400)
        kind = item.get("kind")
        if (
            not quote
            or squash(quote) not in squashed_page
            or kind not in ("LAB", "MEDICATION", "DIAGNOSIS")
        ):
            extraction.dropped += 1  # the words are not on the page: the row is not kept
            continue
        if INSTRUCTION.search(quote):
            extraction.dropped += 1
            extraction.injection_seen = True
            continue
        flags: list[str] = []
        fields: dict[str, Any]
        collected: dt.datetime | None = None
        timed = False
        if kind == "LAB":
            test = _text(item.get("test"), 80)
            value = item.get("value")
            if not test or isinstance(value, bool) or not isinstance(value, (int, float)):
                extraction.dropped += 1
                continue
            if squash(test) not in squash(quote) or not any(
                abs(n - float(value)) < 1e-9 for n in numbers_in(quote)
            ):
                extraction.dropped += (
                    1  # the number is not in the quoted words: possibly misread, so not kept
                )
                continue
            loinc = LAB_NAMES.get(squash(test))
            if loinc is None:
                flags.append("unmatched_test")
            own = _text(item.get("collected_at"), 60)
            source = own if own and squash(own) in squashed_page else extraction.report_collected_at
            collected, timed = parse_when(source)
            if collected is None:
                flags.append("no_date")
            fields = {
                "test": test,
                "loinc_code": loinc,
                "value_num": float(value),
                "unit": _text(item.get("unit"), 40),
            }
            confidence = _confidence(
                0.55,
                mapped=loinc is not None,
                dated=collected is not None,
                timed=timed,
                name_ok=True,
            )
        elif kind == "MEDICATION":
            drug = _text(item.get("drug"), 120)
            if not drug or squash(drug) not in squash(quote):
                extraction.dropped += 1
                continue
            if squash(drug) not in known_drugs and not any(
                squash(drug).startswith(k + " ") for k in known_drugs
            ):
                flags.append("unmatched_drug")
            start = date_only(_text(item.get("start_date"), 60))
            stop = date_only(_text(item.get("stop_date"), 60))
            fields = {
                "description": drug, "strength_text": _text(item.get("strength"), 120), "dose_text": _text(item.get("dose"), 120),
                "start_date": start.isoformat() if start else None, "stop_date": stop.isoformat() if stop else None,
            }  # fmt: skip
            confidence = _confidence(
                0.6,
                mapped="unmatched_drug" not in flags,
                dated=bool(start),
                timed=False,
                name_ok=True,
            )
        else:
            diagnosis = _text(item.get("diagnosis"), 200)
            if not diagnosis or squash(diagnosis) not in squash(quote):
                extraction.dropped += 1
                continue
            onset = date_only(_text(item.get("onset_date"), 60))
            fields = {"description": diagnosis, "onset_date": onset.isoformat() if onset else None}
            confidence = _confidence(
                0.65, mapped=True, dated=bool(onset), timed=False, name_ok=True
            )
        key = (
            kind,
            json.dumps(fields, sort_keys=True),
            collected.isoformat() if collected else None,
        )
        if key in seen:
            continue  # the same finding printed twice (a summary page repeating a result)
        seen.add(key)
        extraction.rows.append(
            {
                "kind": kind, "fields": fields, "collected_at": collected.isoformat() if collected else None,
                "time_known": timed, "source_page": page_no, "source_quote": quote, "confidence": confidence, "flags": flags,
            }
        )  # fmt: skip
