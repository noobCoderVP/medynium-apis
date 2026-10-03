"""User, invitation and entitlement administration (B-3). Doctors with IS_ADMIN only; every change is audited."""

import json
from typing import Any

from medynium_api.core.access import clear_cache
from medynium_api.core.audit.writer import write_auth_event
from medynium_api.core.config import Settings
from medynium_api.core.email import Mailer, get_mailer, invite_email, reset_email
from medynium_api.core.errors import conflict, invalid, not_found
from medynium_api.core.ids import new_uuid
from medynium_api.core.pagination import PageParams
from medynium_api.core.security.tokens import hash_token, new_invite_token
from medynium_api.core.session import Session
from medynium_api.features.admin.repository import AdminRepository
from medynium_api.features.admin.schemas import (
    Entitlements,
    EntitlementsSet,
    InviteCreate,
    InviteCreated,
    InviteItem,
    InvitePage,
    UserItem,
    UserPage,
    UserPatch,
)


def _user(row: dict[str, Any]) -> UserItem:
    return UserItem(
        user_id=row["user_id"], email=row["email"], display_name=row["display_name"], role=row["role_code"],
        is_admin=bool(row["is_admin"]), status=row["status"], supervising_doctor_id=row["supervising_doctor_id"],
        patient_count=int(row["patient_count"]), last_login_at=row["last_login_at"],
    )  # fmt: skip


class AdminService:
    def __init__(
        self,
        settings: Settings,
        repo: AdminRepository | None = None,
        mailer: Mailer | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo or AdminRepository()
        self.mailer = mailer or get_mailer(settings)

    def _link(self, token: str) -> str:
        return f"{self.settings.public_app_url.rstrip('/')}/invite/{token}"

    # Invitations ---------------------------------------------------------------------------------------------------
    def create_invite(self, admin: Session, body: InviteCreate) -> InviteCreated:
        if body.role == "DOCTOR" and body.supervising_doctor_id:
            raise invalid(
                "Only assistants have a supervising doctor.",
                [{"field": "supervising_doctor_id", "problem": "not allowed"}],
            )
        if body.role == "ASSISTANT":
            supervisor = (
                self.repo.user(body.supervising_doctor_id) if body.supervising_doctor_id else None
            )
            if (
                not supervisor
                or supervisor["role_code"] != "DOCTOR"
                or supervisor["status"] != "ACTIVE"
            ):
                raise invalid(
                    "An assistant needs an active supervising doctor.",
                    [{"field": "supervising_doctor_id", "problem": "required"}],
                )
            if body.is_admin:
                raise invalid(
                    "Only doctors can be admins.", [{"field": "is_admin", "problem": "not allowed"}]
                )
            outside = set(body.patient_ids) - self.repo.supervisor_patient_ids(
                supervisor["user_id"]
            )
            if outside:
                raise invalid(
                    "Assistants can only be given patients their supervising doctor has.",
                    [
                        {
                            "field": "patient_ids",
                            "problem": "not all belong to the supervising doctor",
                        }
                    ],
                )
        if self.repo.email_taken(body.email):
            raise conflict("That email already has an account or a pending invitation.")
        token = new_invite_token()
        invite_id = new_uuid()
        self.repo.create_invite(
            (invite_id, body.email, body.display_name, body.role, body.is_admin, body.supervising_doctor_id,
             json.dumps(body.patient_ids), hash_token(token), "INVITE", self.settings.invite_hours, admin.user_id),
        )  # fmt: skip
        write_auth_event(
            "INVITE_CREATED",
            actor_id=admin.user_id,
            email_attempted=body.email,
            detail={"role": body.role},
        )
        expires_at = self.repo.invite_expiry(invite_id)
        link = self._link(token)
        sent = self.mailer.send(
            invite_email(body.display_name, body.role, link, expires_at, body.email)
        )
        return InviteCreated(
            invite_id=invite_id, email=body.email, accept_url=link, expires_at=expires_at,
            email_sent=sent,
        )  # fmt: skip

    def invites(
        self,
        q: str | None,
        status: str | None,
        kind: str | None,
        sort: str | None,
        order: str,
        page: PageParams,
    ) -> InvitePage:
        rows, total = self.repo.invites(q, status, kind, sort, order, page.limit, page.offset)
        return InvitePage(
            items=[
                InviteItem(
                    invite_id=r["invite_id"], email=r["email"], display_name=r["display_name"], role=r["role_code"],
                    kind=r["kind"], status=r["status"], expires_at=r["expires_at"], created_at=r["created_at"],
                )
                for r in rows
            ],
            total=total, limit=page.limit, offset=page.offset,
        )  # fmt: skip

    def revoke_invite(self, invite_id: str) -> None:
        if self.repo.revoke_invite(invite_id) == 0:
            raise not_found()

    # Users -------------------------------------------------------------------------------------------------------
    def list_users(
        self,
        q: str | None,
        role: str | None,
        status: str | None,
        sort: str | None,
        order: str,
        page: PageParams,
    ) -> UserPage:
        rows, total = self.repo.list_users(q, role, status, sort, order, page.limit, page.offset)
        return UserPage(
            items=[_user(r) for r in rows], total=total, limit=page.limit, offset=page.offset
        )

    def get_user(self, user_id: str) -> UserItem:
        row = self.repo.user(user_id)
        if not row:
            raise not_found()
        return _user(row)

    def update_user(self, admin: Session, user_id: str, body: UserPatch) -> UserItem:
        row = self.repo.user(user_id)
        if not row:
            raise not_found()
        losing_admin = (body.status == "DISABLED" and row["is_admin"]) or (
            body.is_admin is False and row["is_admin"]
        )
        if losing_admin and self.repo.admin_count() <= 1:
            raise conflict("There must be at least one active admin.")
        if body.is_admin and row["role_code"] != "DOCTOR":
            raise invalid(
                "Only doctors can be admins.", [{"field": "is_admin", "problem": "not allowed"}]
            )
        if body.display_name is not None or body.is_admin is not None:
            self.repo.update_user(user_id, body.display_name, body.is_admin)
        if body.status == "DISABLED" and row["status"] == "ACTIVE":
            self.repo.call("DEPROVISION_USER", (user_id, admin.user_id))
            self.repo.revoke_sessions(user_id)
        elif body.status == "ACTIVE" and row["status"] != "ACTIVE":
            self.repo.call("ENABLE_USER", (user_id, admin.user_id))
        clear_cache(user_id)
        return self.get_user(user_id)

    def reset_password(self, admin: Session, user_id: str) -> InviteCreated:
        row = self.repo.user(user_id)
        if not row:
            raise not_found()
        token = new_invite_token()
        invite_id = new_uuid()
        self.repo.create_invite(
            (invite_id, row["email"], row["display_name"], row["role_code"], bool(row["is_admin"]),
             row["supervising_doctor_id"], "[]", hash_token(token), "PASSWORD_RESET", self.settings.invite_hours, admin.user_id),
        )  # fmt: skip
        self.repo.revoke_sessions(user_id)
        write_auth_event(
            "INVITE_CREATED",
            user_id=user_id,
            actor_id=admin.user_id,
            detail={"kind": "PASSWORD_RESET"},
        )
        expires_at = self.repo.invite_expiry(invite_id)
        link = self._link(token)
        sent = self.mailer.send(
            reset_email(row["display_name"], link, expires_at, row["email"]),
        )
        return InviteCreated(
            invite_id=invite_id, email=row["email"], accept_url=link, expires_at=expires_at,
            email_sent=sent,
        )  # fmt: skip

    # Entitlements ---------------------------------------------------------------------------------------------------
    def entitlements(self, user_id: str) -> Entitlements:
        if not self.repo.user(user_id):
            raise not_found()
        ids = self.repo.entitlements(user_id)
        return Entitlements(user_id=user_id, patient_ids=ids, total=len(ids))

    def set_entitlements(self, admin: Session, user_id: str, body: EntitlementsSet) -> Entitlements:
        if not self.repo.user(user_id):
            raise not_found()
        result = self.repo.set_entitlements(user_id, sorted(set(body.patient_ids)), admin.user_id)
        if not result.get("ok"):
            error = result.get("error", "")
            if error == "unknown_patient":
                raise invalid(
                    "Some patient ids do not exist.",
                    [
                        {
                            "field": "patient_ids",
                            "problem": f"unknown: {', '.join(result.get('patient_ids', []))}",
                        }
                    ],
                )
            if error == "not_supervisor_patient":
                raise invalid(
                    "An assistant can only have patients the supervising doctor has.",
                    [
                        {
                            "field": "patient_ids",
                            "problem": "not all belong to the supervising doctor",
                        }
                    ],
                )
            raise not_found()
        clear_cache()
        return self.entitlements(user_id)
