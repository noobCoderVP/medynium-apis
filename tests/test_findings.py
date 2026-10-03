"""Findings: what each decision requires, and the service flow with a fake repository (no Snowflake)."""

import datetime as dt
from typing import Any

import pytest

from medynium_api.core.errors import ApiError
from medynium_api.core.session import Session
from medynium_api.features.findings import service as service_module
from medynium_api.features.findings.rules import check_update, is_open
from medynium_api.features.findings.schemas import FindingCreate, FindingUpdate
from medynium_api.features.findings.service import FindingService

TODAY = dt.date(2026, 10, 3)
COLLEAGUES = frozenset({"u-colleague"})


def update(**kwargs: Any) -> FindingUpdate:
    return FindingUpdate(**kwargs)


def check(current: str, body: FindingUpdate) -> None:
    check_update(current, body, "u-me", TODAY, COLLEAGUES)


def problem_fields(error: ApiError) -> list[str]:
    return [d["field"] for d in (error.details or [])]


# Rules --------------------------------------------------------------------------------------------------------------


def test_acknowledging_a_new_finding_needs_nothing_more() -> None:
    check("NEW", update(status="ACKNOWLEDGED"))


def test_dismissing_needs_a_reason() -> None:
    with pytest.raises(ApiError) as caught:
        check("NEW", update(status="DISMISSED", reason="  "))
    assert problem_fields(caught.value) == ["reason"]
    check("NEW", update(status="DISMISSED", reason="Known and monitored"))


def test_flagging_needs_a_follow_up_date_that_is_not_in_the_past() -> None:
    with pytest.raises(ApiError):
        check("NEW", update(status="FLAGGED"))
    with pytest.raises(ApiError):
        check("NEW", update(status="FLAGGED", follow_up_on=dt.date(2026, 10, 2)))
    check("NEW", update(status="FLAGGED", follow_up_on=TODAY))


def test_a_flagged_finding_can_be_flagged_again_with_a_new_date() -> None:
    check("FLAGGED", update(status="FLAGGED", follow_up_on=dt.date(2026, 11, 1)))


def test_escalating_needs_a_colleague_who_has_the_patient() -> None:
    for target in (None, "u-me", "u-stranger"):
        with pytest.raises(ApiError) as caught:
            check("NEW", update(status="ESCALATED", assigned_to=target))
        assert problem_fields(caught.value) == ["assigned_to"]
    check("NEW", update(status="ESCALATED", assigned_to="u-colleague"))


def test_repeating_the_same_state_is_refused() -> None:
    with pytest.raises(ApiError):
        check("ACKNOWLEDGED", update(status="ACKNOWLEDGED"))


def test_open_means_someone_still_has_to_act() -> None:
    assert [is_open(s) for s in ("NEW", "FLAGGED", "ESCALATED")] == [True, True, True]
    assert [is_open(s) for s in ("ACKNOWLEDGED", "DISMISSED")] == [False, False]


# Service ------------------------------------------------------------------------------------------------------------


def row(status: str = "NEW", **extra: Any) -> dict[str, Any]:
    base = {
        "finding_id": "FND-1",
        "patient_id": "P-1",
        "answer_id": "ANS-1",
        "consideration_id": "C1",
        "summary": "May warrant clinician review.",
        "status": status,
        "reason": None,
        "follow_up_on": None,
        "assigned_to": None,
        "created_by": "u-me",
        "created_at": dt.datetime(2026, 10, 3),
        "updated_at": None,
    }
    return {**base, **extra}


class FakeRepo:
    def __init__(self, statement: str | None = "May warrant clinician review.") -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self._statement = statement
        self.created = 0

    def existing(self, *_a: Any) -> dict[str, Any] | None:
        return next(iter(self.rows.values()), None)

    def statement(self, *_a: Any) -> str | None:
        return self._statement

    def create(self, _role: str, finding_id: str, *_a: Any) -> dict[str, Any]:
        self.created += 1
        self.rows[finding_id] = row(finding_id=finding_id)
        return self.rows[finding_id]

    def get(self, _role: str, finding_id: str) -> dict[str, Any] | None:
        return self.rows.get(finding_id)

    def update(self, _role: str, finding_id: str, status: str, *_a: Any) -> dict[str, Any]:
        self.rows[finding_id] = {**self.rows[finding_id], "status": status}
        return self.rows[finding_id]

    def names(self, _ids: set[str]) -> dict[str, str]:
        return {"u-me": "Dr Me"}

    def colleagues(self, _patient_id: str) -> list[dict[str, Any]]:
        return [{"user_id": "u-colleague", "display_name": "Dr Co", "role_code": "DOCTOR"}]


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    log: list[Any] = []
    monkeypatch.setattr(service_module, "require_patient", lambda *_a: None)
    monkeypatch.setattr(
        service_module, "write_audit", lambda _s, entry, **_k: log.append(entry) or "A"
    )
    return log


def session() -> Session:
    return Session(
        "a" * 8 + "-0000-0000-0000-" + "b" * 12, "DOCTOR", False, "s", 1, dt.datetime(2030, 1, 1)
    )


def test_raising_a_finding_is_audited_and_repeating_does_not_duplicate(audits: list[Any]) -> None:
    repo = FakeRepo()
    service = FindingService(repo)  # type: ignore[arg-type]
    body = FindingCreate(answer_id="ANS-1", consideration_id="C1")
    first = service.create(session(), "P-1", body)
    assert first.status == "NEW" and first.created_by_name == "Dr Me"
    assert [a.action for a in audits] == ["RAISE_FINDING"]
    repo.rows = {first.finding_id: row(finding_id=first.finding_id)}
    again = service.create(session(), "P-1", body)
    assert again.finding_id == first.finding_id and repo.created == 1 and len(audits) == 1


def test_a_statement_that_is_not_the_callers_is_not_found(audits: list[Any]) -> None:
    service = FindingService(FakeRepo(statement=None))  # type: ignore[arg-type]
    with pytest.raises(ApiError) as caught:
        service.create(session(), "P-1", FindingCreate(answer_id="ANS-9", consideration_id="C1"))
    assert caught.value.code.value == "not_found"
    assert audits == []


def test_a_decision_is_checked_saved_and_audited(audits: list[Any]) -> None:
    repo = FakeRepo()
    repo.rows["FND-1"] = row()
    service = FindingService(repo)  # type: ignore[arg-type]
    done = service.update(session(), "FND-1", update(status="ACKNOWLEDGED"))
    assert done.status == "ACKNOWLEDGED"
    assert (
        audits[0].action == "DECIDE_FINDING" and "NEW to ACKNOWLEDGED" in audits[0].outcome_detail
    )


def test_an_incomplete_decision_changes_and_audits_nothing(audits: list[Any]) -> None:
    repo = FakeRepo()
    repo.rows["FND-1"] = row()
    service = FindingService(repo)  # type: ignore[arg-type]
    with pytest.raises(ApiError):
        service.update(session(), "FND-1", update(status="DISMISSED"))
    assert repo.rows["FND-1"]["status"] == "NEW" and audits == []


def test_an_unknown_finding_is_not_found(audits: list[Any]) -> None:
    service = FindingService(FakeRepo())  # type: ignore[arg-type]
    with pytest.raises(ApiError) as caught:
        service.update(session(), "FND-NOPE", update(status="ACKNOWLEDGED"))
    assert caught.value.code.value == "not_found"
