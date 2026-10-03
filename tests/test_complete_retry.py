"""A transient Cortex failure is retried once; anything else, or a second failure, is a clean agent_unavailable."""

from contextlib import contextmanager
from typing import Any

import pytest
from snowflake.connector.errors import ProgrammingError

from medynium_api.core.cortex import complete as complete_module
from medynium_api.core.errors import ApiError, ErrorCode

REPLY = '{"choices": [{"messages": "ok"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}'


class Cursor:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def execute(self, *_: Any, **__: Any) -> None:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome

    def fetchone(self) -> dict[str, str]:
        return {"R": REPLY}


def patch(monkeypatch: pytest.MonkeyPatch, outcomes: list[Any]) -> Cursor:
    cursor = Cursor(outcomes)

    @contextmanager
    def fake() -> Any:
        yield cursor

    monkeypatch.setattr(complete_module, "service_cursor", fake)
    return cursor


def failure(errno: int) -> ProgrammingError:
    return ProgrammingError(msg="canceled", errno=errno)


def test_a_transient_failure_is_retried_once_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = patch(monkeypatch, [failure(604), None])
    assert complete_module.complete("m", [{"role": "user", "content": "x"}]).text == "ok"
    assert cursor.calls == 2


def test_a_second_failure_is_a_clean_agent_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = patch(monkeypatch, [failure(604), failure(604)])
    with pytest.raises(ApiError) as caught:
        complete_module.complete("m", [{"role": "user", "content": "x"}])
    assert caught.value.code is ErrorCode.AGENT_UNAVAILABLE and cursor.calls == 2


def test_other_errors_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = patch(monkeypatch, [failure(1003)])
    with pytest.raises(ApiError):
        complete_module.complete("m", [{"role": "user", "content": "x"}])
    assert cursor.calls == 1
