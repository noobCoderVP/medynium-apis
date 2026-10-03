"""User, invitation and entitlement administration. Doctors with IS_ADMIN only (otherwise 403)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.errors import ErrorBody
from medynium_api.core.pagination import Paging, SortOrder
from medynium_api.core.session import AdminSession
from medynium_api.features.admin.schemas import (
    Entitlements,
    EntitlementsSet,
    InviteCreate,
    InviteCreated,
    InvitePage,
    UserItem,
    UserPage,
    UserPatch,
)
from medynium_api.features.admin.service import AdminService

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    responses={403: {"model": ErrorBody}, 404: {"model": ErrorBody}},
)


def get_service(settings: Annotated[Settings, Depends(get_settings)]) -> AdminService:
    return AdminService(settings)


Service = Annotated[AdminService, Depends(get_service)]


@router.post("/invites", status_code=201)
def create_invite(body: InviteCreate, admin: AdminSession, service: Service) -> InviteCreated:
    """Create an invitation. The link is emailed (when email is configured) and returned once; only its hash is stored."""
    return service.create_invite(admin, body)


@router.get("/invites")
def list_invites(
    admin: AdminSession,
    service: Service,
    page: Paging,
    q: str | None = None,
    status: Literal["PENDING", "ACCEPTED", "REVOKED", "EXPIRED"] | None = None,
    kind: Literal["INVITE", "PASSWORD_RESET"] | None = None,
    sort: Literal["created", "expires", "email"] = "created",
    order: SortOrder = "desc",
) -> InvitePage:
    return service.invites(q, status, kind, sort, order, page)


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(invite_id: str, admin: AdminSession, service: Service) -> None:
    service.revoke_invite(invite_id)


@router.get("/users")
def list_users(
    admin: AdminSession,
    service: Service,
    page: Paging,
    q: str | None = None,
    role: Literal["DOCTOR", "ASSISTANT"] | None = None,
    status: Literal["ACTIVE", "DISABLED"] | None = None,
    sort: Literal["name", "email", "role", "last_login", "patients"] = "name",
    order: SortOrder = "asc",
) -> UserPage:
    return service.list_users(q, role, status, sort, order, page)


@router.get("/users/{user_id}")
def get_user(user_id: str, admin: AdminSession, service: Service) -> UserItem:
    return service.get_user(user_id)


@router.patch("/users/{user_id}")
def update_user(user_id: str, body: UserPatch, admin: AdminSession, service: Service) -> UserItem:
    """Rename, grant or remove admin, disable or re-enable. Disabling ends the user's sessions."""
    return service.update_user(admin, user_id, body)


@router.post("/users/{user_id}/reset-password", status_code=201)
def reset_password(user_id: str, admin: AdminSession, service: Service) -> InviteCreated:
    """A one-time link that lets the user set a new password. Their sessions end now."""
    return service.reset_password(admin, user_id)


@router.get("/users/{user_id}/entitlements")
def get_entitlements(user_id: str, admin: AdminSession, service: Service) -> Entitlements:
    return service.entitlements(user_id)


@router.put("/users/{user_id}/entitlements")
def put_entitlements(
    user_id: str, body: EntitlementsSet, admin: AdminSession, service: Service
) -> Entitlements:
    """Replace the user's patient set. Assistants may only have their supervising doctor's patients."""
    return service.set_entitlements(admin, user_id, body)
