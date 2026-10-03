"""Key-pair JWT for the Cortex REST APIs (spike S-A/S-B): iss = ACCOUNT.USER.SHA256:<fingerprint>."""

import base64
import hashlib
import threading
import time

import jwt
from cryptography.hazmat.primitives import serialization

from medynium_api.core.config import Settings
from medynium_api.core.errors import ApiError, ErrorCode

LIFETIME_SECONDS = 3000
_lock = threading.Lock()
_cached: tuple[float, str] | None = None


def _build(settings: Settings) -> str:
    pem = settings.private_key_pem
    if pem is None:
        raise ApiError(ErrorCode.AGENT_UNAVAILABLE, "The AI service is not configured.")
    key = serialization.load_pem_private_key(pem, password=None)
    public = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(public).digest()).decode()
    qualified = f"{settings.snowflake_account.upper()}.{settings.snowflake_api_user.upper()}"
    now = int(time.time())
    claims = {
        "iss": f"{qualified}.{fingerprint}",
        "sub": qualified,
        "iat": now,
        "exp": now + LIFETIME_SECONDS,
    }
    return jwt.encode(claims, pem, algorithm="RS256")


def jwt_token(settings: Settings) -> str:
    global _cached
    with _lock:
        if _cached is None or _cached[0] < time.time() + 120:
            _cached = (time.time() + LIFETIME_SECONDS, _build(settings))
        return _cached[1]


def rest_headers(settings: Settings, role: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {jwt_token(settings)}",
        "X-Snowflake-Authorization-Token-Type": "KEYPAIR_JWT",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    headers["X-Snowflake-Role"] = role or settings.snowflake_api_role
    return headers
