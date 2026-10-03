import datetime as dt
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from medynium_api.core.pagination import Page

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RoleCode = Literal["DOCTOR", "ASSISTANT"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InviteCreate(Strict):
    email: str = Field(max_length=254)
    display_name: str = Field(min_length=1, max_length=120)
    role: RoleCode
    is_admin: bool = False
    supervising_doctor_id: str | None = None
    patient_ids: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL.match(value):
            raise ValueError("not a valid email address")
        return value


class InviteCreated(BaseModel):
    invite_id: str
    email: str
    accept_url: str
    expires_at: dt.datetime


class InviteItem(BaseModel):
    invite_id: str
    email: str
    display_name: str
    role: RoleCode
    kind: Literal["INVITE", "PASSWORD_RESET"]
    status: str
    expires_at: dt.datetime
    created_at: dt.datetime


class UserItem(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: RoleCode
    is_admin: bool
    status: str
    supervising_doctor_id: str | None
    patient_count: int
    last_login_at: dt.datetime | None


UserPage = Page[UserItem]


class UserPatch(Strict):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    is_admin: bool | None = None
    status: Literal["ACTIVE", "DISABLED"] | None = None


class Entitlements(BaseModel):
    user_id: str
    patient_ids: list[str]
    total: int


class EntitlementsSet(Strict):
    patient_ids: list[str] = Field(max_length=2000)
