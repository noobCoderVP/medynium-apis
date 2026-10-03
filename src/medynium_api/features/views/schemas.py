import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Kind = Literal["SAVED_VIEW", "VISIT_BRIEF"]


class ViewPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind
    patient_id: str
    content: dict[str, Any]


class ViewPreview(BaseModel):
    preview_id: str
    kind: Kind
    patient_id: str
    title: str
    content: dict[str, Any]
    expires_at: dt.datetime


class ViewSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_id: str
    approved: bool = Field(description="Must be true; nothing is saved without approval (FR-22).")


class SavedView(BaseModel):
    view_id: str
    kind: Kind
    patient_id: str
    title: str | None
    content: dict[str, Any]
    approved_at: dt.datetime | None
    created_at: dt.datetime
