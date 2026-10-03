"""The two auth cookies. HttpOnly always; Secure everywhere except local development."""

from fastapi import Response

from medynium_api.core.config import Settings

ACCESS_COOKIE = "med_access"
REFRESH_COOKIE = "med_refresh"


def set_auth_cookies(response: Response, settings: Settings, access: str, refresh: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE,
        access,
        max_age=settings.access_token_minutes * 60,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=settings.refresh_token_days * 86400,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=settings.refresh_cookie_path)
