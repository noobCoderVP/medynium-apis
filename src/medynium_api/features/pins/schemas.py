import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class PinCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_id: str = Field(min_length=3, max_length=40)
    evidence_id: str = Field(min_length=1, max_length=20)
    note: str | None = Field(default=None, max_length=500)


class Pin(BaseModel):
    pin_id: str
    answer_id: str
    evidence_id: str
    label: str | None
    note: str | None
    created_at: dt.datetime


class PinList(BaseModel):
    items: list[Pin]
