from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RoleCode = Literal["DOCTOR", "ASSISTANT"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(Strict):
    email: str = Field(min_length=3, max_length=254, examples=["sharma@demo.medynium"])
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: RoleCode
    is_admin: bool


class LoginResponse(BaseModel):
    user: UserOut
    session_expires_at: datetime


class MeResponse(UserOut):
    supervising_doctor_id: str | None = None
    patient_count: int
    permissions: list[str]


class ChangePasswordRequest(Strict):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class InvitePreview(BaseModel):
    email: str
    display_name: str
    role: RoleCode
    expires_at: datetime
    kind: Literal["INVITE", "PASSWORD_RESET"]


class AcceptInviteRequest(Strict):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=120)


class AcceptInviteResponse(BaseModel):
    email: str
