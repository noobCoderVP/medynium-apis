"""Unit tests for the primitives the access chain stands on. No Snowflake needed."""

import time
from datetime import date

import jwt
import pytest

from medynium_api.core.config import Settings
from medynium_api.core.errors import ApiError, ErrorCode
from medynium_api.core.ids import role_for_user
from medynium_api.core.schemas import flags_from
from medynium_api.core.security.passwords import hash_password, password_problems, verify_password
from medynium_api.core.security.ratelimit import RateLimiter
from medynium_api.core.security.tokens import (
    create_access_token,
    decode_access_token,
    hash_token,
    new_refresh_token,
)

SETTINGS = Settings(session_secret="x" * 40)  # type: ignore[arg-type]
USER = "7f0c2f2e-5b43-4a43-9a4e-2f4d0d8c1a11"


def test_password_hash_verifies_and_is_argon2id() -> None:
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)


def test_verify_without_a_hash_is_always_false_but_still_works() -> None:
    assert verify_password("anything-at-all-123", None) is False


def test_password_policy() -> None:
    assert password_problems("short", "a@b.com")
    assert any(
        "email" in p for p in password_problems("sharma@demo.medynium", "sharma@demo.medynium")
    )
    assert any(
        "common" in p
        for p in password_problems("password1234"[:11] + "1", "x@y.com")
        + password_problems("administrator", "x@y.com")
    )
    assert password_problems("a-long-unique-passphrase-9", "x@y.com") == []
    assert any("email" in p for p in password_problems("sharma", "sharma@demo.medynium"))


def test_access_token_round_trip_and_tamper_detection() -> None:
    token = create_access_token(
        SETTINGS, user_id=USER, role="DOCTOR", is_admin=True, token_version=3, session_id="s1"
    )
    claims = decode_access_token(SETTINGS, token)
    assert claims and claims.user_id == USER and claims.is_admin and claims.token_version == 3
    assert decode_access_token(SETTINGS, token + "x") is None
    assert decode_access_token(Settings(session_secret="y" * 40), token) is None  # type: ignore[arg-type]


def test_expired_and_alg_none_tokens_are_rejected() -> None:
    expired = jwt.encode(
        {"iss": "medynium", "sub": USER, "role": "DOCTOR", "sid": "s", "exp": int(time.time()) - 5},
        "x" * 40,
        algorithm="HS256",
    )
    assert decode_access_token(SETTINGS, expired) is None
    none_alg = jwt.encode(
        {"iss": "medynium", "sub": USER, "role": "DOCTOR", "sid": "s"}, None, algorithm="none"
    )
    assert decode_access_token(SETTINGS, none_alg) is None


def test_unknown_role_claim_is_rejected() -> None:
    token = jwt.encode(
        {"iss": "medynium", "sub": USER, "role": "ROOT", "sid": "s", "exp": int(time.time()) + 60},
        "x" * 40,
        algorithm="HS256",
    )
    assert decode_access_token(SETTINGS, token) is None


def test_refresh_tokens_are_random_and_hashed() -> None:
    a, b = new_refresh_token(), new_refresh_token()
    assert a != b and len(a) >= 40
    assert hash_token(a) != a and len(hash_token(a)) == 64


def test_role_names_come_only_from_a_valid_uuid() -> None:
    assert role_for_user(USER) == "U_7F0C2F2E5B434A439A4E2F4D0D8C1A11"
    for bad in ("x", "'; DROP ROLE X; --", USER + "00", ""):
        with pytest.raises(ValueError):
            role_for_user(bad)


def test_rate_limiter_blocks_then_recovers() -> None:
    limiter = RateLimiter(limit=2, window_seconds=0.2)
    limiter.check("k")
    limiter.check("k")
    with pytest.raises(ApiError) as caught:
        limiter.check("k")
    assert caught.value.code is ErrorCode.RATE_LIMITED and "Retry-After" in (
        caught.value.headers or {}
    )
    limiter.check("other")
    time.sleep(0.25)
    limiter.check("k")


def test_change_flags() -> None:
    flags = flags_from(2, True, True, False, date(2026, 10, 2))
    assert [f.type for f in flags] == ["NEW_LAB", "NEW_MEDICATION", "RECENT_EMERGENCY"]
    assert flags[0].label == "2 new labs" and flags[2].label == "ED visit 2 Oct"
    assert flags_from(1, False, False, False, None)[0].label == "1 new lab"
    assert flags_from(0, False, False, False, None) == []


def test_settings_refuse_development_defaults_when_deployed() -> None:
    with pytest.raises(RuntimeError):
        Settings(app_env="production").assert_safe_for_environment()
    with pytest.raises(RuntimeError):
        Settings(app_env="production", session_secret="short").assert_safe_for_environment()  # type: ignore[arg-type]
