"""The last active admin can never be disabled or demoted. A stub repository stands in for Snowflake, so this
runs without touching any shared account (the live version of this check once disabled the real demo admin)."""

from datetime import UTC, datetime
from typing import Any

import pytest

from medynium_api.core.config import Settings
from medynium_api.core.errors import ApiError, ErrorCode
from medynium_api.core.session import Session
from medynium_api.features.admin.schemas import UserPatch
from medynium_api.features.admin.service import AdminService

ADMIN = Session(
    user_id="admin-1", role="DOCTOR", is_admin=True, session_id="s", token_version=1,
    expires_at=datetime(2099, 1, 1, tzinfo=UTC),
)  # fmt: skip


class StubRepo:
    def __init__(self, admins: int) -> None:
        self.admins = admins
        self.calls: list[str] = []

    def user(self, user_id: str) -> dict[str, Any]:
        return {
            "user_id": user_id, "email": "a@x", "display_name": "A", "role_code": "DOCTOR",
            "is_admin": True, "status": "ACTIVE", "supervising_doctor_id": None,
            "last_login_at": None, "patient_count": 0, "created_at": datetime(2026, 1, 1),
        }  # fmt: skip

    def admin_count(self) -> int:
        return self.admins

    def update_user(self, *args: Any) -> None:
        self.calls.append("update_user")

    def call(self, procedure: str, args: tuple[Any, ...]) -> dict[str, Any]:
        self.calls.append(procedure)
        return {"ok": True}

    def revoke_sessions(self, user_id: str) -> None:
        self.calls.append("revoke_sessions")


def service(admins: int) -> tuple[AdminService, StubRepo]:
    repo = StubRepo(admins)
    return AdminService(Settings(), repo=repo, mailer=object()), repo  # type: ignore[arg-type]


@pytest.mark.parametrize("patch", [UserPatch(status="DISABLED"), UserPatch(is_admin=False)])
def test_the_only_admin_cannot_be_disabled_or_demoted(patch: UserPatch) -> None:
    svc, repo = service(admins=1)
    with pytest.raises(ApiError) as caught:
        svc.update_user(ADMIN, "admin-1", patch)
    assert caught.value.code is ErrorCode.CONFLICT
    assert repo.calls == []  # nothing was changed


def test_with_two_admins_one_can_be_disabled() -> None:
    svc, repo = service(admins=2)
    svc.update_user(ADMIN, "admin-1", UserPatch(status="DISABLED"))
    assert "DEPROVISION_USER" in repo.calls
