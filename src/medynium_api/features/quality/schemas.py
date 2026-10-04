import datetime as dt
from typing import Literal

from pydantic import BaseModel


class GoldenCase(BaseModel):
    seq: int
    group: str | None
    question: str
    result: Literal["PASS", "FAIL"]
    route: str | None
    detail: str | None


class GoldenRun(BaseModel):
    run_id: str
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    status: str
    total: int
    passed: int
    cases: list[GoldenCase]


class GoldenRunList(BaseModel):
    latest: GoldenRun | None
    history: list[GoldenRun]
