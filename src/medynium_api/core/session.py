"""The signed-in caller, from the access-token cookie. Every route except those marked public needs one.

The access token is verified without a database call (ADR-004). The Snowflake role is derived from the user id,
never taken from the request.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, Request

from medynium_api.core.config import get_settings
from medynium_api.core.errors import forbidden, unauthorized
from medynium_api.core.ids import role_for_user
from medynium_api.core.security.cookies import ACCESS_COOKIE
from medynium_api.core.security.tokens import decode_access_token


@dataclass(frozen=True)
class Session:
    user_id: str
    role: Literal["DOCTOR", "ASSISTANT"]
    is_admin: bool
    session_id: str
    token_version: int
    expires_at: datetime

    @property
    def snowflake_role(self) -> str:
        return role_for_user(self.user_id)


def optional_session(request: Request) -> Session | None:
    """The caller if their access cookie is valid, otherwise None (for routes that work either way)."""
    token = request.cookies.get(ACCESS_COOKIE)
    claims = decode_access_token(get_settings(), token) if token else None
    if claims is None:
        return None
    return Session(
        user_id=claims.user_id,
        role=claims.role,
        is_admin=claims.is_admin,
        session_id=claims.session_id,
        token_version=claims.token_version,
        expires_at=claims.expires_at,
    )


def require_session(request: Request) -> Session:
    session = optional_session(request)
    if session is None:
        raise unauthorized()
    return session


def require_admin(session: Annotated[Session, Depends(require_session)]) -> Session:
    if not (session.role == "DOCTOR" and session.is_admin):
        raise forbidden()
    return session


def require_doctor(session: Annotated[Session, Depends(require_session)]) -> Session:
    if session.role != "DOCTOR":
        raise forbidden()
    return session


CurrentSession = Annotated[Session, Depends(require_session)]
MaybeSession = Annotated[Session | None, Depends(optional_session)]
AdminSession = Annotated[Session, Depends(require_admin)]
DoctorSession = Annotated[Session, Depends(require_doctor)]
