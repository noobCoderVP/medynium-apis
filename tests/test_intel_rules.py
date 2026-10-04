"""Attention, changes and gaps are fixed rules over rows: the same rows always give the same, checkable items."""

import datetime as dt
from decimal import Decimal

from medynium_api.core.intel import rules

AS_OF = dt.date(2026, 10, 2)


def lab(name: str, value: str, prev: str | None, flag: str | None, new: bool = True, at: dt.date = dt.date(2026, 9, 18)) -> dict:  # fmt: skip
    return {
        "latest_lab_id": f"L-{name}", "short_name": name, "latest_value": Decimal(value), "unit": "u",
        "latest_at": dt.datetime.combine(at, dt.time()), "previous_value": None if prev is None else Decimal(prev),
        "previous_at": dt.datetime(2026, 6, 12), "abnormal_flag": flag, "is_new_since_last_visit": new,
    }  # fmt: skip


HEAD = {
    "has_recent_emergency": True, "last_encounter_kind": "EMERGENCY", "last_encounter_id": "E-1",
    "last_encounter_date": dt.date(2026, 10, 2), "last_encounter_label": "Chest discomfort",
}  # fmt: skip


def test_an_abnormal_new_result_is_high_and_says_how_it_moved() -> None:
    items = rules.attention({}, [lab("eGFR", "42", "47", "LOW")], [], [], AS_OF)
    assert items[0].severity == "high" and items[0].kind == "abnormal_lab"
    assert items[0].title == "eGFR 42 u (low)"
    assert items[0].detail == "Down from 47 on 12 Jun 2026 (-11%)"
    assert items[0].source.type == "lab" and items[0].source.query == {"lab": "eGFR"}


def test_an_old_abnormal_result_is_moderate_and_an_in_range_result_that_moved_a_lot_is_info() -> (
    None
):
    items = rules.attention(
        {},
        [lab("K", "5.8", "5.7", "HIGH", new=False), lab("Cr", "1.7", "1.4", None)],
        [],
        [],
        AS_OF,
    )
    assert [(i.kind, i.severity) for i in items] == [
        ("abnormal_lab", "moderate"),
        ("lab_movement", "info"),
    ]
    assert items[1].title == "Cr up 21%"


def test_a_small_in_range_move_is_not_worth_a_line() -> None:
    assert rules.attention({}, [lab("Na", "139", "140", None)], [], [], AS_OF) == []


def test_new_medicine_diagnosis_emergency_and_pending_items_are_ranked() -> None:
    events = [
        {
            "event_type": "MEDICATION_START",
            "title": "Apixaban started",
            "summary": None,
            "event_date": dt.date(2026, 10, 1),
            "record_id": "M-1",
        },
        {
            "event_type": "CLAIM",
            "title": "Claim",
            "summary": None,
            "event_date": dt.date(2026, 10, 1),
            "record_id": "C-1",
        },
    ]
    pending = [
        {
            "kind": "FOLLOW_UP",
            "title": "Recheck potassium",
            "detail": "Flagged",
            "due_date": dt.date(2026, 9, 30),
            "raised_at": dt.datetime(2026, 9, 20),
            "source_id": "F-1",
        },
        {
            "kind": "ABNORMAL_LAB",
            "title": "dup",
            "detail": None,
            "due_date": None,
            "raised_at": None,
            "source_id": "L-1",
        },
        {
            "kind": "REPORT_TO_REVIEW",
            "title": "Report waiting",
            "detail": "3 items",
            "due_date": None,
            "raised_at": dt.datetime(2026, 10, 1),
            "source_id": "R-1",
        },
    ]
    items = rules.attention(HEAD, [], events, pending, AS_OF)
    assert [i.kind for i in items[:2]] == ["emergency_visit", "follow_up"]
    assert {i.kind for i in items[2:]} == {"report_to_review", "medication_start"}
    assert [i.severity for i in items] == ["high", "high", "moderate", "moderate"]
    assert "overdue" in (items[1].detail or "")  # due 30 Sep, as of 2 Oct
    assert all(i.title != "dup" for i in items)  # covered by the lab rule, not repeated


def test_attention_is_capped() -> None:
    labs = [lab(f"T{n}", "9", "5", "HIGH") for n in range(12)]
    assert len(rules.attention({}, labs, [], [], AS_OF)) == rules.MAX_ATTENTION


def test_resolve_since() -> None:
    assert rules.resolve_since("previous_visit", dt.date(2026, 8, 14), AS_OF) == (dt.date(2026, 8, 14), "since the previous visit on 14 Aug 2026")  # fmt: skip
    assert rules.resolve_since("previous_visit", None, AS_OF)[0] == dt.date(2026, 7, 4)  # type: ignore[index]
    assert rules.resolve_since("1y", None, AS_OF)[0] == dt.date(2025, 10, 2)  # type: ignore[index]
    assert rules.resolve_since("2026-01-05", None, AS_OF)[0] == dt.date(2026, 1, 5)  # type: ignore[index]
    assert rules.resolve_since("last week", None, AS_OF) is None


def test_changes_are_grouped_with_lab_movement_and_skip_claims_and_old_results() -> None:
    events = [
        {
            "event_type": "MEDICATION_CHANGE",
            "title": "Metformin dose raised",
            "summary": "to 1000 mg",
            "event_date": dt.date(2026, 9, 20),
            "record_id": "M-2",
        },
        {
            "event_type": "LAB_PANEL",
            "title": "Lab panel",
            "summary": "x",
            "event_date": dt.date(2026, 9, 18),
            "record_id": "L-9",
        },
        {
            "event_type": "CLAIM",
            "title": "Claim",
            "summary": None,
            "event_date": dt.date(2026, 9, 18),
            "record_id": "C-1",
        },
    ]
    labs = [lab("eGFR", "42", "47", "LOW"), lab("TSH", "2", "2", None, at=dt.date(2026, 5, 1))]
    reports = [
        {
            "report_id": "R-1",
            "filename": "cardiology.pdf",
            "rows_kept": 4,
            "extracted_at": dt.datetime(2026, 9, 25),
        }
    ]
    result = rules.changes(dt.date(2026, 8, 14), "since the previous visit", labs, events, reports)
    assert result.counts == {"DOCUMENT": 1, "MEDICATION": 1, "LAB": 1}
    titles = [i.title for i in result.items]
    assert "eGFR 47 to 42 u (low)" in titles and "Metformin dose raised" in titles
    assert not any("TSH" in t or "Claim" in t or t == "Lab panel" for t in titles)
    lab_item = next(i for i in result.items if i.category == "LAB")
    assert lab_item.direction == "down"


def meds(*names: str) -> list[dict]:
    return [
        {"medication_id": f"M-{n}", "drug_id": f"D-{n}", "drug_name": n.title(), "description": n}
        for n in names
    ]


def test_monitoring_gaps_use_the_age_of_the_latest_result() -> None:
    labs = [
        lab("HbA1c", "7", None, None, at=dt.date(2026, 1, 10)),
        lab("eGFR", "60", None, None, at=dt.date(2026, 9, 1)),
    ]
    found = rules.gaps(meds("metformin"), labs, [], 1, AS_OF)
    assert [g.title for g in found] == ["HbA1c not seen in the last 6 months"]
    assert "latest 10 Jan 2026" in (found[0].detail or "")
    assert "not a rule for this patient" in (found[0].detail or "")


def test_a_missing_test_is_reported_once_even_if_a_medicine_and_a_diagnosis_both_ask() -> None:
    found = rules.gaps(meds("metformin"), [], ["Type 2 diabetes mellitus"], 1, AS_OF)
    assert [g.title for g in found].count("HbA1c not seen in the last 6 months") == 1
    assert any(g.title.startswith("eGFR") for g in found)


def test_unindexed_medicine_and_unknown_allergies_are_gaps_and_nothing_else_is_invented() -> None:
    unindexed = [
        {
            "medication_id": "M-9",
            "drug_id": None,
            "drug_name": "Perampanel",
            "description": "perampanel",
        }
    ]
    found = rules.gaps(unindexed, [], [], 0, AS_OF)
    assert [g.kind for g in found] == ["label_not_indexed", "allergy_unknown"]
    assert rules.gaps([], [], [], 2, AS_OF) == []
