"""Emailed one-time sign-in codes, with no table behind them.

After the password is accepted the API mints a short-lived signed challenge that holds only an HMAC of the code, so
neither the challenge nor the logs reveal it. The code itself travels by email. A code is single use (the challenge
id is remembered until it would have expired) and attempts are capped per user. Like the rate limiter, the used-id
set lives in memory, which is correct for the single instance we run.
"""

import hashlib
import hmac
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta

import jwt

from medynium_api.core.config import Settings
from medynium_api.core.security.ratelimit import RateLimiter

OTP_TYPE = "otp"
_used: dict[str, float] = {}
_lock = threading.Lock()
otp_limiter = RateLimiter(limit=5, window_seconds=600)


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _digest(settings: Settings, user_id: str, challenge_id: str, code: str) -> str:
    key = settings.session_secret.get_secret_value().encode()
    return hmac.new(key, f"{user_id}:{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


def create_challenge(settings: Settings, user_id: str, code: str) -> str:
    now = datetime.now(UTC)
    challenge_id = secrets.token_urlsafe(12)
    payload = {
        "typ": OTP_TYPE,
        "sub": user_id,
        "jti": challenge_id,
        "cdh": _digest(settings, user_id, challenge_id, code),
        "iat": now,
        "exp": now + timedelta(minutes=settings.otp_minutes),
    }
    return jwt.encode(payload, settings.session_secret.get_secret_value(), algorithm="HS256")


def verify_challenge(settings: Settings, challenge: str, code: str) -> str | None:
    """The user id when the code matches a live, unused challenge; otherwise None. A match is consumed."""
    try:
        data = jwt.decode(
            challenge,
            settings.session_secret.get_secret_value(),
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "jti", "cdh"]},
        )
    except jwt.PyJWTError:
        return None
    if data.get("typ") != OTP_TYPE:
        return None
    user_id, challenge_id = str(data["sub"]), str(data["jti"])
    otp_limiter.check(f"otp:{user_id}")
    expected = _digest(settings, user_id, challenge_id, code.strip())
    if not hmac.compare_digest(expected, str(data["cdh"])):
        return None
    with _lock:
        now = time.time()
        for key in [k for k, until in _used.items() if until < now]:
            del _used[key]
        if challenge_id in _used:
            return None
        _used[challenge_id] = float(data["exp"])
    return user_id


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}{'*' * max(1, len(name) - 1)}@{domain}"
