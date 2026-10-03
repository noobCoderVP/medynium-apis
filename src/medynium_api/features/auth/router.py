from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.errors import ErrorBody
from medynium_api.core.security.cookies import REFRESH_COOKIE, clear_auth_cookies, set_auth_cookies
from medynium_api.core.session import CurrentSession, MaybeSession
from medynium_api.features.auth.schemas import (
    AcceptInviteRequest,
    AcceptInviteResponse,
    ChangePasswordRequest,
    InvitePreview,
    LoginRequest,
    LoginResponse,
    MeResponse,
)
from medynium_api.features.auth.service import AuthService

router = APIRouter(tags=["auth"])
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_service(settings: SettingsDep) -> AuthService:
    return AuthService(settings)


Service = Annotated[AuthService, Depends(get_service)]


def client(request: Request) -> tuple[str | None, str | None]:
    return (request.client.host if request.client else None), request.headers.get("user-agent")


@router.post("/auth/login", responses={401: {"model": ErrorBody}, 429: {"model": ErrorBody}})
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    service: Service,
    settings: SettingsDep,
) -> LoginResponse:
    """Start a session. Sets the `med_access` and `med_refresh` cookies."""
    ip, agent = client(request)
    result, tokens = service.login(body.email, body.password, ip, agent)
    set_auth_cookies(response, settings, tokens.access, tokens.refresh)
    return result


@router.post("/auth/refresh", status_code=204, responses={401: {"model": ErrorBody}})
def refresh(request: Request, response: Response, service: Service, settings: SettingsDep) -> None:
    """Rotate both cookies using the refresh cookie. A reused refresh token revokes the session."""
    tokens = service.refresh(request.cookies.get(REFRESH_COOKIE))
    set_auth_cookies(response, settings, tokens.access, tokens.refresh)


@router.post("/auth/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    session: MaybeSession,
    service: Service,
    settings: SettingsDep,
) -> None:
    """Revoke the session and clear the cookies. Safe to call when already signed out."""
    service.logout(session, request.cookies.get(REFRESH_COOKIE))
    clear_auth_cookies(response, settings)


@router.get("/me")
def me(session: CurrentSession, service: Service) -> MeResponse:
    """The signed-in user, their role and what they may do."""
    return service.me(session)


@router.post("/auth/password", status_code=204)
def change_password(
    body: ChangePasswordRequest, request: Request, session: CurrentSession, service: Service
) -> None:
    """Change your password. Other sessions are revoked."""
    service.change_password(session, body, client(request)[0])


@router.get("/auth/invites/{token}", responses={404: {"model": ErrorBody}})
def invite_preview(token: str, service: Service) -> InvitePreview:
    """Public. Who an invitation or reset link is for."""
    return service.invite_preview(token)


@router.post("/auth/invites/accept", status_code=201, responses={404: {"model": ErrorBody}})
def accept_invite(
    body: AcceptInviteRequest, request: Request, service: Service
) -> AcceptInviteResponse:
    """Public. Set a password and activate the account (or complete a password reset)."""
    return AcceptInviteResponse(email=service.accept(body, client(request)[0]))
