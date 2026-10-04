import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Status = Literal["OPEN", "ADDED", "DECLINED"]


class DrugRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None


class DrugRequest(BaseModel):
    request_id: str
    drug: str
    note: str | None
    status: Status
    requested_at: dt.datetime
    requested_by_name: str | None = None
    decided_by_name: str | None = None
    decided_at: dt.datetime | None = None
    decision_note: str | None = None
    already_open: bool = Field(
        default=False, description="This drug was already requested by you and is still open."
    )


class DrugRequestList(BaseModel):
    items: list[DrugRequest]


class RequestDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ADDED", "DECLINED"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None


class UnlabelledMedicine(BaseModel):
    medicine: str
    patients: int


class Coverage(BaseModel):
    snapshot_date: dt.date | None
    drugs_known: int
    drugs_indexed: int
    chunks: int
    nlem_known: int = Field(
        description="Known drugs flagged as on the National List of Essential Medicines."
    )
    nlem_indexed: int
    not_indexed: list[str] = Field(
        description="Known drugs with no label indexed (a US label is not available or not added)."
    )
    unlabelled_in_use: list[UnlabelledMedicine] = Field(
        description="Medicines on active lists with no linked label, most used first, among the patients the caller can see."
    )
    open_requests: int
    note: str
