from fastapi import APIRouter

from medynium_api.core.errors import not_implemented
from medynium_api.core.session import CurrentSession
from medynium_api.schemas import LoginRequest, MeResponse

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=MeResponse, summary="Start a session (Slice 3)")
def login(body: LoginRequest) -> MeResponse:
    raise not_implemented("POST /auth/login")


@router.post("/auth/logout", status_code=204, summary="End the session")
def logout(session: CurrentSession) -> None:
    raise not_implemented("POST /auth/logout")


@router.get("/me", response_model=MeResponse, summary="Current user and role")
def me(session: CurrentSession) -> MeResponse:
    raise not_implemented("GET /me")
