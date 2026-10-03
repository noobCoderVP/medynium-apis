"""Sign-in, refresh rotation with reuse detection, password change, invitation acceptance (B-2).

Unknown email, wrong password, disabled and locked accounts all return the same `unauthorized` message, and the
same hashing work is done in every case, so neither the response nor its timing reveals which accounts exist.
"""

import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import structlog

from medynium_api.core.audit.writer import write_auth_event
from medynium_api.core.config import Settings
from medynium_api.core.email import (
    Mailer,
    get_mailer,
    otp_email,
    password_changed_email,
)
from medynium_api.core.errors import (
    ApiError,
    ErrorCode,
    unauthorized,
)
from medynium_api.core.ids import new_uuid
from medynium_api.core.security import otp
from medynium_api.core.security.passwords import hash_password, verify_password
from medynium_api.core.security.ratelimit import login_limiter
from medynium_api.core.security.tokens import (
    create_access_token,
    hash_token,
    new_refresh_token,
)
from medynium_api.core.session import Session
from medynium_api.features.auth.invites import check_password
from medynium_api.features.auth.repository import AuthRepository, utc_now
from medynium_api.features.auth.schemas import (
    ChangePasswordRequest,
    LoginResponse,
    MeResponse,
    OtpChallenge,
    UserOut,
)

BAD_CREDENTIALS = "Email or password is incorrect."

log = structlog.get_logger()


@dataclass(frozen=True)
class Tokens:
    access: str
    refresh: str


def permissions_for(role: str, is_admin: bool) -> list[str]:
    perms = ["patients:read", "copilot:ask", "agent:actions"]
    if role == "DOCTOR":
        perms.append("golden:run")
        if is_admin:
            perms.append("admin:users")
    return perms


def user_out(row: dict[str, Any]) -> UserOut:
    return UserOut(
        user_id=row["user_id"], email=row["email"], display_name=row["display_name"],
        role=row["role_code"], is_admin=bool(row["is_admin"]),
    )  # fmt: skip


class AuthService:
    def __init__(
        self,
        settings: Settings,
        repo: AuthRepository | None = None,
        mailer: Mailer | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo or AuthRepository()
        self.mailer = mailer or get_mailer(settings)

    # Sign in -----------------------------------------------------------------------------------------------------
    def login(
        self, email: str, password: str, ip: str | None, user_agent: str | None
    ) -> tuple[LoginResponse | OtpChallenge, Tokens | None]:
        email = email.strip().lower()
        login_limiter.check(f"ip:{ip}")
        login_limiter.check(f"email:{email}")
        row = self.repo.user_by_email(email)
        verified = verify_password(password, row["password_hash"] if row else None)
        now = utc_now()
        locked = bool(row and row["locked_until"] and row["locked_until"] > now)
        active = bool(row and row["status"] == "ACTIVE")

        if not (row and verified and active and not locked):
            if row and active and not verified and not locked:
                self.repo.record_failure(
                    row["user_id"],
                    self.settings.login_max_failures,
                    self.settings.login_lock_minutes,
                )
                if row["failed_logins"] + 1 >= self.settings.login_max_failures:
                    write_auth_event(
                        "LOCKOUT", user_id=row["user_id"], ip_address=ip, user_agent=user_agent
                    )
            write_auth_event(
                "LOGIN_FAILURE", user_id=row["user_id"] if row else None, email_attempted=email,
                ip_address=ip, user_agent=user_agent,
            )  # fmt: skip
            reason = (
                "unknown_user"
                if not row
                else "inactive"
                if not active
                else "locked"
                if locked
                else "bad_password"
            )
            log.warning("login_failed", reason=reason)
            raise unauthorized(BAD_CREDENTIALS)

        if self.settings.login_otp_enabled:
            return self._issue_otp(row, ip, user_agent), None
        return self._finish_login(row, ip, user_agent)

    def _finish_login(
        self, row: dict[str, Any], ip: str | None, user_agent: str | None
    ) -> tuple[LoginResponse, Tokens]:
        self.repo.record_success(row["user_id"])
        tokens, expires = self._start_session(row, ip, user_agent)
        write_auth_event(
            "LOGIN_SUCCESS", user_id=row["user_id"], ip_address=ip, user_agent=user_agent
        )
        log.info("login_ok", user_id=row["user_id"], role=row["role_code"])
        return LoginResponse(user=user_out(row), session_expires_at=expires), tokens

    # Second step: an emailed six-digit code ----------------------------------------------------------------------
    def _issue_otp(
        self, row: dict[str, Any], ip: str | None, user_agent: str | None
    ) -> OtpChallenge:
        code = otp.new_code()
        message = otp_email(row["display_name"], code, self.settings.otp_minutes, row["email"])
        if not self.mailer.send(message):
            raise ApiError(
                ErrorCode.SERVICE_UNAVAILABLE, "We could not send your sign-in code. Try again."
            )
        write_auth_event("OTP_SENT", user_id=row["user_id"], ip_address=ip, user_agent=user_agent)
        return OtpChallenge(
            challenge=otp.create_challenge(self.settings, row["user_id"], code),
            email_hint=otp.mask_email(row["email"]),
            expires_in_minutes=self.settings.otp_minutes,
        )

    def verify_otp(
        self, challenge: str, code: str, ip: str | None, user_agent: str | None
    ) -> tuple[LoginResponse, Tokens]:
        login_limiter.check(f"ip:{ip}")
        user_id = otp.verify_challenge(self.settings, challenge, code)
        row = self.repo.user_by_id(user_id) if user_id else None
        if not row or row["status"] != "ACTIVE":
            write_auth_event("OTP_FAILURE", user_id=user_id, ip_address=ip, user_agent=user_agent)
            raise unauthorized("That code is incorrect or has expired.")
        return self._finish_login(row, ip, user_agent)

    def _start_session(
        self, row: dict[str, Any], ip: str | None, user_agent: str | None
    ) -> tuple[Tokens, datetime]:
        session_id = new_uuid()
        refresh = f"{session_id}.{new_refresh_token()}"
        self.repo.create_session(
            session_id,
            row["user_id"],
            hash_token(refresh),
            self.settings.refresh_token_days,
            user_agent,
            ip,
        )
        access = create_access_token(
            self.settings, user_id=row["user_id"], role=row["role_code"], is_admin=bool(row["is_admin"]),
            token_version=int(row["token_version"]), session_id=session_id,
        )  # fmt: skip
        return Tokens(access, refresh), utc_now() + timedelta(days=self.settings.refresh_token_days)

    # Refresh with rotation and reuse detection -----------------------------------------------------------------
    def refresh(self, refresh_token: str | None) -> Tokens:
        if not refresh_token or "." not in refresh_token:
            raise unauthorized()
        session_id = refresh_token.split(".", 1)[0]
        session = self.repo.session(session_id)
        if not session or session["revoked_at"] or session["expired"]:
            raise unauthorized()
        presented = hash_token(refresh_token)
        if session["previous_hash"] and hmac.compare_digest(presented, session["previous_hash"]):
            # An already-rotated token came back: someone copied it. End the whole session.
            self.repo.revoke_session(session_id)
            write_auth_event("REFRESH_REUSE", user_id=session["user_id"])
            raise unauthorized()
        if not hmac.compare_digest(presented, session["refresh_hash"]):
            raise unauthorized()
        user = self.repo.user_by_id(session["user_id"])
        if not user or user["status"] != "ACTIVE":
            self.repo.revoke_session(session_id)
            raise unauthorized()
        new_refresh = f"{session_id}.{new_refresh_token()}"
        self.repo.rotate_session(session_id, hash_token(new_refresh), presented)
        access = create_access_token(
            self.settings, user_id=user["user_id"], role=user["role_code"], is_admin=bool(user["is_admin"]),
            token_version=int(user["token_version"]), session_id=session_id,
        )  # fmt: skip
        write_auth_event("REFRESH", user_id=user["user_id"])
        return Tokens(access, new_refresh)

    def logout(self, session: Session | None, refresh_token: str | None) -> None:
        session_id = session.session_id if session else (refresh_token or "").split(".", 1)[0]
        if session_id:
            self.repo.revoke_session(session_id)
            write_auth_event("LOGOUT", user_id=session.user_id if session else None)

    # Current user ------------------------------------------------------------------------------------------------
    def me(self, session: Session) -> MeResponse:
        row = self.repo.user_by_id(session.user_id)
        if not row or row["status"] != "ACTIVE":
            raise unauthorized()
        base = user_out(row)
        return MeResponse(
            **base.model_dump(), supervising_doctor_id=row["supervising_doctor_id"],
            patient_count=self.repo.patient_count(row["user_id"]),
            permissions=permissions_for(row["role_code"], bool(row["is_admin"])),
        )  # fmt: skip

    def change_password(
        self, session: Session, body: ChangePasswordRequest, ip: str | None
    ) -> None:
        row = self.repo.user_by_id(session.user_id)
        if not row or not verify_password(body.current_password, row["password_hash"]):
            raise unauthorized("Current password is incorrect.")
        check_password(body.new_password, row["email"])
        self.repo.set_password(row["user_id"], hash_password(body.new_password))
        self.repo.revoke_user_sessions(row["user_id"], except_session=session.session_id)
        write_auth_event("PASSWORD_CHANGE", user_id=row["user_id"], ip_address=ip)
        self.mailer.send(password_changed_email(row["display_name"], row["email"]))
