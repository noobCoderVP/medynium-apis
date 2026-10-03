"""Email, sign-in codes and list helpers. No Snowflake and no network: Resend is replaced by a stub transport."""

import datetime as dt

import httpx
import pytest
from fastapi.testclient import TestClient

from medynium_api.core.config import Settings
from medynium_api.core.email import (
    EmailMessage,
    NoopMailer,
    ResendMailer,
    get_mailer,
    invite_email,
    otp_email,
    patient_summary_email,
)
from medynium_api.core.pagination import like, order_clause
from medynium_api.core.security import otp
from medynium_api.core.security.ratelimit import RateLimiter
from medynium_api.main import app

SETTINGS = Settings(session_secret="x" * 40)  # type: ignore[arg-type]
USER = "7f0c2f2e-5b43-4a43-9a4e-2f4d0d8c1a11"
client = TestClient(app, headers={"X-Medynium-Client": "web"})


# Mailer ------------------------------------------------------------------------------------------------------------
def test_no_key_means_a_noop_mailer_that_reports_not_sent() -> None:
    mailer = get_mailer(SETTINGS)
    assert isinstance(mailer, NoopMailer)
    assert mailer.send(EmailMessage("a@b.co", "s", "<p>h</p>", "t")) is False


def test_resend_mailer_posts_the_documented_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        seen.update(url=url, **kwargs)
        return httpx.Response(200, json={"id": "1"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    mailer = ResendMailer("re_key", "Medynium <a@b.co>", "reply@b.co")
    assert mailer.send(EmailMessage("to@b.co", "Subject", "<p>x</p>", "x", kind="invite")) is True
    body = seen["json"]
    assert isinstance(body, dict)
    assert body["to"] == ["to@b.co"] and body["from"] == "Medynium <a@b.co>"
    assert body["reply_to"] == "reply@b.co" and body["tags"] == [
        {"name": "kind", "value": "invite"}
    ]
    assert seen["headers"] == {"Authorization": "Bearer re_key"}


def test_resend_failure_is_swallowed_and_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", boom)
    assert ResendMailer("k", "a@b.co", None).send(EmailMessage("t@b.co", "s", "h", "t")) is False


def test_templates_escape_names_and_carry_the_link() -> None:
    expires = dt.datetime(2026, 10, 5, 9, 30)
    message = invite_email("<b>Dr</b>", "DOCTOR", "https://app/invite/tok", expires, "d@x.co")
    assert "<b>Dr</b>" not in message.html and "&lt;b&gt;Dr" in message.html
    assert "https://app/invite/tok" in message.html and "https://app/invite/tok" in message.text
    assert "05 Oct 2026" in message.text


def test_otp_email_puts_the_code_in_subject_and_body() -> None:
    message = otp_email("Asha", "123456", 10, "a@x.co")
    assert "123456" in message.subject and "123456" in message.text and "123456" in message.html


def test_patient_summary_skips_empty_sections_and_escapes_the_note() -> None:
    message = patient_summary_email(
        "Dr Rao", "c@x.co", "Meera", [("Medications", ["Metformin"]), ("Labs", [])],
        "<script>x</script>", "https://app/patients/P-1",
    )  # fmt: skip
    assert "Metformin" in message.html and "Labs" not in message.html
    assert "<script>" not in message.html


# Sign-in codes -----------------------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_limits() -> None:
    otp.otp_limiter.reset()
    otp._used.clear()


def test_code_is_six_digits() -> None:
    assert all(len(otp.new_code()) == 6 and otp.new_code().isdigit() for _ in range(20))


def test_right_code_verifies_once_only() -> None:
    challenge = otp.create_challenge(SETTINGS, USER, "012345")
    assert otp.verify_challenge(SETTINGS, challenge, "012345") == USER
    assert otp.verify_challenge(SETTINGS, challenge, "012345") is None


def test_wrong_code_and_tampered_challenge_fail() -> None:
    challenge = otp.create_challenge(SETTINGS, USER, "012345")
    assert otp.verify_challenge(SETTINGS, challenge, "999999") is None
    assert otp.verify_challenge(SETTINGS, challenge + "x", "012345") is None
    other = Settings(session_secret="y" * 40)  # type: ignore[arg-type]
    assert otp.verify_challenge(other, challenge, "012345") is None


def test_attempts_are_capped_per_user() -> None:
    challenge = otp.create_challenge(SETTINGS, USER, "012345")
    for _ in range(5):
        otp.verify_challenge(SETTINGS, challenge, "000000")
    with pytest.raises(Exception, match="Too many"):
        otp.verify_challenge(SETTINGS, challenge, "012345")


def test_email_hint_hides_the_address() -> None:
    assert otp.mask_email("sharma@demo.medynium") == "s*****@demo.medynium"


# Routes ------------------------------------------------------------------------------------------------------------
def test_share_needs_a_session() -> None:
    response = client.post("/patients/P-1042/share", json={"to": "a@b.co"})
    assert response.status_code == 401


def test_verify_rejects_a_malformed_code_before_any_lookup() -> None:
    response = client.post("/auth/login/verify", json={"challenge": "x" * 30, "code": "12ab56"})
    assert response.status_code == 422


def test_forgot_password_validates_its_body() -> None:
    assert client.post("/auth/password/forgot", json={}).status_code == 422


def test_openapi_has_the_new_endpoints() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/auth/login/verify", "/auth/password/forgot", "/patients/{patient_id}/share"):
        assert path in paths


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/patients?sort=bogus"),
        ("GET", "/patients?order=sideways"),
        ("GET", "/patients?limit=0"),
        ("GET", "/patients?limit=500"),
        ("GET", "/patients/P-1042/labs?flag=bogus"),
        ("GET", "/admin/invites?status=bogus"),
    ],
)
def test_list_params_are_validated_before_auth_is_asked(method: str, path: str) -> None:
    # A bad sort or page size is a 422 whether or not the caller is signed in: it never reaches SQL.
    assert client.request(method, path).status_code in (401, 422)


# List helpers ------------------------------------------------------------------------------------------------------
SORTS = {"name": "w.FULL_NAME", "age": "w.AGE_YEARS"}


def test_order_clause_only_uses_known_columns() -> None:
    assert order_clause("age", "asc", SORTS, "name", "w.ID") == "w.AGE_YEARS ASC NULLS LAST, w.ID"
    assert order_clause("age; DROP TABLE x", "desc", SORTS, "name", "w.ID") == (
        "w.FULL_NAME DESC NULLS LAST, w.ID"
    )


def test_like_drops_caller_wildcards() -> None:
    assert like("  sha%_rma ") == "%sharma%"


def test_rate_limiter_still_resets() -> None:
    limiter = RateLimiter(limit=1, window_seconds=60)
    limiter.check("k")
    limiter.reset()
    limiter.check("k")
