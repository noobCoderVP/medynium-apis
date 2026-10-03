from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.errors import ErrorBody
from medynium_api.core.security.cookies import REFRESH_COOKIE, clear_auth_cookies, set_auth_cookies
from medynium_api.core.session import CurrentSession, MaybeSession
from medynium_api.features.auth.invites import InviteService
from medynium_api.features.auth.schemas import (
    AcceptInviteRequest,
    AcceptInviteResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    InvitePreview,
    LoginRequest,
    LoginResponse,
    MeResponse,
    OtpChallenge,
    OtpVerifyRequest,
    RefreshRequest,
    TokenPair,
)
from medynium_api.features.auth.service import AuthService

router = APIRouter(tags=["auth"])
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_service(settings: SettingsDep) -> AuthService:
    return AuthService(settings)


Service = Annotated[AuthService, Depends(get_service)]


def get_invites(settings: SettingsDep) -> InviteService:
    return InviteService(settings)


Invites = Annotated[InviteService, Depends(get_invites)]


def is_mobile(request: Request) -> bool:
    return request.headers.get("x-medynium-client") == "mobile"


def client(request: Request) -> tuple[str | None, str | None]:
    return (request.client.host if request.client else None), request.headers.get("user-agent")


@router.post("/auth/login", responses={401: {"model": ErrorBody}, 429: {"model": ErrorBody}})
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    service: Service,
    settings: SettingsDep,
) -> LoginResponse | OtpChallenge:
    """Start a session and set the `med_access` and `med_refresh` cookies.

    When email codes are required (LOGIN_OTP_ENABLED) no session starts yet: an `OtpChallenge` comes back and the
    client finishes with `POST /auth/login/verify`.
    """
    ip, agent = client(request)
    result, tokens = service.login(body.email, body.password, ip, agent)
    if tokens is not None:
        if is_mobile(request) and isinstance(result, LoginResponse):
            return result.model_copy(
                update={"tokens": TokenPair(access=tokens.access, refresh=tokens.refresh)}
            )
        set_auth_cookies(response, settings, tokens.access, tokens.refresh)
    return result


@router.post("/auth/login/verify", responses={401: {"model": ErrorBody}, 429: {"model": ErrorBody}})
def verify_login(
    body: OtpVerifyRequest,
    request: Request,
    response: Response,
    service: Service,
    settings: SettingsDep,
) -> LoginResponse:
    """Finish a sign-in with the six-digit code that was emailed. Sets the auth cookies."""
    ip, agent = client(request)
    result, tokens = service.verify_otp(body.challenge, body.code, ip, agent)
    if is_mobile(request):
        return result.model_copy(
            update={"tokens": TokenPair(access=tokens.access, refresh=tokens.refresh)}
        )
    set_auth_cookies(response, settings, tokens.access, tokens.refresh)
    return result


@router.post("/auth/password/forgot", status_code=204, responses={429: {"model": ErrorBody}})
def forgot_password(body: ForgotPasswordRequest, request: Request, service: Invites) -> None:
    """Public. Emails a one-time reset link when the address belongs to an active account. Always 204."""
    service.forgot_password(body.email, client(request)[0])


@router.post("/auth/refresh", status_code=204, responses={401: {"model": ErrorBody}})
def refresh(request: Request, response: Response, service: Service, settings: SettingsDep) -> None:
    """Rotate both cookies using the refresh cookie. A reused refresh token revokes the session."""
    tokens = service.refresh(request.cookies.get(REFRESH_COOKIE))
    set_auth_cookies(response, settings, tokens.access, tokens.refresh)


@router.post("/auth/mobile/refresh", responses={401: {"model": ErrorBody}})
def refresh_mobile(body: RefreshRequest, service: Service) -> TokenPair:
    """Mobile only: rotate the bearer tokens. Same rotation and reuse detection as the cookie refresh."""
    tokens = service.refresh(body.refresh)
    return TokenPair(access=tokens.access, refresh=tokens.refresh)


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
def invite_preview(token: str, service: Invites) -> InvitePreview:
    """Public. Who an invitation or reset link is for."""
    return service.invite_preview(token)


@router.post("/auth/invites/accept", status_code=201, responses={404: {"model": ErrorBody}})
def accept_invite(
    body: AcceptInviteRequest, request: Request, service: Invites
) -> AcceptInviteResponse:
    """Public. Set a password and activate the account (or complete a password reset)."""
    return AcceptInviteResponse(email=service.accept(body, client(request)[0]))
