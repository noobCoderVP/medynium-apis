"""Invitations, password-reset links and the emails that go with them (B-2)."""

from datetime import timedelta

from medynium_api.core.audit.writer import write_auth_event
from medynium_api.core.config import Settings
from medynium_api.core.email import (
    Mailer,
    get_mailer,
    password_changed_email,
    reset_email,
    welcome_email,
)
from medynium_api.core.errors import ApiError, ErrorCode, conflict, invalid, not_found
from medynium_api.core.ids import new_uuid
from medynium_api.core.security.passwords import hash_password, password_problems
from medynium_api.core.security.ratelimit import login_limiter
from medynium_api.core.security.tokens import hash_token, new_invite_token
from medynium_api.features.auth.repository import AuthRepository, utc_now
from medynium_api.features.auth.schemas import AcceptInviteRequest, InvitePreview


def check_password(password: str, email: str) -> None:
    problems = password_problems(password, email)
    if problems:
        raise invalid(
            "The password does not meet the rules.",
            [{"field": "password", "problem": p} for p in problems],
        )


class InviteService:
    def __init__(
        self,
        settings: Settings,
        repo: AuthRepository | None = None,
        mailer: Mailer | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo or AuthRepository()
        self.mailer = mailer or get_mailer(settings)

    def _url(self, path: str) -> str:
        return f"{self.settings.public_app_url.rstrip('/')}{path}"

    def forgot_password(self, email: str, ip: str | None) -> None:
        """Always succeeds from the caller's side, so the answer never says whether an account exists."""
        email = email.strip().lower()
        login_limiter.check(f"ip:{ip}")
        login_limiter.check(f"forgot:{email}")
        row = self.repo.user_by_email(email)
        if not row or row["status"] != "ACTIVE":
            return
        token = new_invite_token()
        self.repo.create_reset(
            (new_uuid(), row["email"], row["display_name"], row["role_code"], bool(row["is_admin"]),
             row["supervising_doctor_id"], hash_token(token), self.settings.invite_hours, row["user_id"]),
        )  # fmt: skip
        expires = utc_now() + timedelta(hours=self.settings.invite_hours)
        link = self._url(f"/invite/{token}")
        self.mailer.send(reset_email(row["display_name"], link, expires, row["email"]))
        write_auth_event("PASSWORD_RESET_REQUESTED", user_id=row["user_id"], ip_address=ip)

    def invite_preview(self, token: str) -> InvitePreview:
        invite = self.repo.valid_invite(hash_token(token))
        if not invite:
            raise not_found()
        return InvitePreview(
            email=invite["email"], display_name=invite["display_name"], role=invite["role_code"],
            expires_at=invite["expires_at"], kind=invite["kind"],
        )  # fmt: skip

    def accept(self, body: AcceptInviteRequest, ip: str | None) -> str:
        invite = self.repo.valid_invite(hash_token(body.token))
        if not invite:
            raise not_found()
        check_password(body.password, invite["email"])
        password_hash = hash_password(body.password)

        if invite["kind"] == "PASSWORD_RESET":
            user = self.repo.user_by_email(invite["email"])
            if not user:
                raise not_found()
            self.repo.set_password(user["user_id"], password_hash)
            self.repo.revoke_user_sessions(user["user_id"])
            self.repo.mark_invite_accepted(invite["invite_id"])
            write_auth_event(
                "PASSWORD_CHANGE", user_id=user["user_id"], ip_address=ip, detail={"via": "reset"}
            )
            self.mailer.send(password_changed_email(user["display_name"], user["email"]))
            return str(invite["email"])

        user_id = new_uuid()
        name = body.display_name or invite["display_name"]
        result = self.repo.provision_user(
            (user_id, invite["email"], name, invite["role_code"],
             bool(invite["is_admin"]), invite["supervising_doctor_id"], password_hash, invite["invited_by"]),
        )  # fmt: skip
        if not result.get("ok"):
            if result.get("error") == "already_exists":
                raise conflict("An account with this email already exists.")
            raise ApiError(ErrorCode.INVALID_REQUEST, "The invitation can no longer be accepted.")
        if invite["patient_ids"]:
            granted = self.repo.set_entitlements(
                user_id, invite["patient_ids"], invite["invited_by"] or user_id
            )
            if not granted.get("ok"):
                raise conflict(
                    "Some patients on the invitation can no longer be assigned. Ask your admin."
                )
        self.repo.mark_invite_accepted(invite["invite_id"])
        write_auth_event(
            "INVITE_ACCEPTED", user_id=user_id, actor_id=invite["invited_by"], ip_address=ip
        )
        self.mailer.send(welcome_email(name, self._url("/sign-in"), invite["email"]))
        return str(invite["email"])
