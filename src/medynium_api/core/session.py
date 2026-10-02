"""Session dependency. Every route except /auth/login and /health requires one (SRS 4.2).

Real sign-in (one Snowflake connection per app user, role-scoped) lands in Slice 3.
Until then no session can exist, so protected routes answer 401.
"""

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Request

from medynium_api.core.errors import ApiError, ErrorCode


@dataclass(frozen=True)
class Session:
    user: str
    role: Literal["MED_DOCTOR", "MED_ASSISTANT"]


def require_session(request: Request) -> Session:
    session = getattr(request.state, "session", None)
    if session is None:
        raise ApiError(ErrorCode.UNAUTHORIZED, "Sign in to continue.")
    return session  # type: ignore[no-any-return]


CurrentSession = Annotated[Session, Depends(require_session)]
