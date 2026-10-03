"""Access tokens (HS256 JWT, 15 minutes) and refresh tokens (random, hashed at rest). See ADR-004."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

from medynium_api.core.config import Settings

ISSUER = "medynium"
ALGORITHM = "HS256"


@dataclass(frozen=True)
class AccessClaims:
    user_id: str
    role: Literal["DOCTOR", "ASSISTANT"]
    is_admin: bool
    token_version: int
    session_id: str
    expires_at: datetime


def create_access_token(
    settings: Settings,
    *,
    user_id: str,
    role: str,
    is_admin: bool,
    token_version: int,
    session_id: str,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": ISSUER,
        "sub": user_id,
        "role": role,
        "adm": is_admin,
        "ver": token_version,
        "sid": session_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.session_secret.get_secret_value(), algorithm=ALGORITHM)


def decode_access_token(settings: Settings, token: str) -> AccessClaims | None:
    """Return the claims, or None for any invalid, expired or malformed token."""
    try:
        data = jwt.decode(
            token,
            settings.session_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["exp", "sub", "role", "sid"]},
        )
        if data["role"] not in ("DOCTOR", "ASSISTANT"):
            return None
        return AccessClaims(
            user_id=str(data["sub"]),
            role=data["role"],
            is_admin=bool(data.get("adm", False)),
            token_version=int(data.get("ver", 0)),
            session_id=str(data["sid"]),
            expires_at=datetime.fromtimestamp(int(data["exp"]), UTC),
        )
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def new_invite_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
