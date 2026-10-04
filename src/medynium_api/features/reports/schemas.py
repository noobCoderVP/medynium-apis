import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Status = Literal["UPLOADED", "PARSING", "EXTRACTED", "REVIEWED", "REJECTED", "FAILED"]
RowStatus = Literal["PENDING", "ACCEPTED", "EDITED", "REJECTED", "APPROVED"]
RowKind = Literal["LAB", "MEDICATION", "DIAGNOSIS"]
Identity = Literal["MATCH", "MISMATCH", "UNKNOWN"]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportSummary(BaseModel):
    report_id: str
    patient_id: str
    filename: str
    mime_type: str
    size_bytes: int
    page_count: int | None
    status: Status
    status_detail: str | None
    uploaded_at: dt.datetime
    uploaded_by_name: str | None = None
    extracted_at: dt.datetime | None
    name_on_report: str | None
    identity_status: Identity | None
    identity_confirmed: bool
    rows_kept: int | None
    rows_dropped: int | None
    rows_waiting: int = Field(
        default=0, description="Rows a doctor has not yet approved or rejected."
    )
    duplicate: bool = Field(
        default=False, description="This exact file was already uploaded for this patient."
    )


class ReportRow(BaseModel):
    row_id: str
    kind: RowKind
    fields: dict[str, Any]
    collected_at: dt.datetime | None
    time_known: bool
    source_page: int
    source_quote: str
    confidence: float
    flags: list[str] = Field(
        description="unmatched_test, unmatched_drug, no_date, duplicate (already in the record), already_listed."
    )
    status: RowStatus
    record_id: str | None
    version: int


class ReportPage(BaseModel):
    page: int
    text: str


class ReportDetail(ReportSummary):
    rows: list[ReportRow]
    pages: list[ReportPage]


class ReportList(BaseModel):
    items: list[ReportSummary]


# Review ---------------------------------------------------------------------------------------------------------
class RowEdit(Strict):
    """Replace what was read from a report row. A lab needs a supported test (its LOINC code) and a collection time."""

    version: int = Field(ge=1)
    fields: dict[str, Any]
    collected_at: dt.datetime | None = None

    @model_validator(mode="after")
    def _small(self) -> "RowEdit":
        if len(self.fields) > 12 or any(len(str(v)) > 300 for v in self.fields.values()):
            raise ValueError("the edited fields are too large")
        return self


class RowDecision(Strict):
    version: int = Field(ge=1)


class RowResult(BaseModel):
    row_id: str
    status: RowStatus
    version: int


class ApproveBody(Strict):
    confirm_identity: bool = Field(
        default=False,
        description="Needed when the name on the report does not match this patient: the doctor confirms it is theirs.",
    )


class ApproveStarted(BaseModel):
    report_id: str
    queued: int = Field(
        description="Rows being written to the record now; the report page shows them as approved."
    )
