"""Error contract: {"error": code, "message": text} (SRS 4.2, docs/api/README.md).

A denied patient must be indistinguishable from a missing one (SEC-05), so `not_found` always uses the same
message and never names the resource.
"""

from enum import StrEnum
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger()


class ErrorCode(StrEnum):
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    ACTION_NOT_ALLOWED = "action_not_allowed"
    AGENT_UNAVAILABLE = "agent_unavailable"
    TIMEOUT = "timeout"
    SERVICE_UNAVAILABLE = "service_unavailable"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    INVALID_REQUEST = "invalid_request"
    NOT_IMPLEMENTED = "not_implemented"
    INTERNAL = "internal_error"


class ErrorBody(BaseModel):
    error: ErrorCode
    message: str
    details: list[dict[str, Any]] | None = None


NOT_FOUND_MESSAGE = "The requested resource was not found."

STATUS: dict[ErrorCode, int] = {
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.ACTION_NOT_ALLOWED: 403,
    ErrorCode.AGENT_UNAVAILABLE: 503,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
    ErrorCode.CONFLICT: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.INVALID_REQUEST: 422,
    ErrorCode.NOT_IMPLEMENTED: 501,
    ErrorCode.INTERNAL: 500,
}


class ApiError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code
        self.message = message or (NOT_FOUND_MESSAGE if code is ErrorCode.NOT_FOUND else code.value)
        self.status_code = STATUS[code]
        self.details = details
        self.headers = headers
        super().__init__(self.message)


def not_found() -> ApiError:
    return ApiError(ErrorCode.NOT_FOUND)


def unauthorized(message: str = "Sign in to continue.") -> ApiError:
    return ApiError(ErrorCode.UNAUTHORIZED, message)


def forbidden(message: str = "You do not have access to this.") -> ApiError:
    return ApiError(ErrorCode.FORBIDDEN, message)


def invalid(message: str, details: list[dict[str, Any]] | None = None) -> ApiError:
    return ApiError(ErrorCode.INVALID_REQUEST, message, details=details)


def conflict(message: str) -> ApiError:
    return ApiError(ErrorCode.CONFLICT, message)


def not_implemented(what: str) -> ApiError:
    return ApiError(ErrorCode.NOT_IMPLEMENTED, f"{what} is not implemented yet.")


def _response(
    code: ErrorCode,
    message: str,
    status: int,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorBody(error=code, message=message, details=details).model_dump(
        mode="json", exclude_none=True
    )
    return JSONResponse(body, status, headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        log.info("api_error", code=exc.code.value, status=exc.status_code)
        return _response(exc.code, exc.message, exc.status_code, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "problem": e["msg"]}
            for e in exc.errors()
        ]
        return _response(ErrorCode.INVALID_REQUEST, "The request was not valid.", 422, details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _response(ErrorCode.NOT_FOUND, NOT_FOUND_MESSAGE, 404)
        if exc.status_code == 405:
            return _response(ErrorCode.INVALID_REQUEST, "Method not allowed.", 405)
        return _response(ErrorCode.INVALID_REQUEST, str(exc.detail), exc.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_exception", exc_type=type(exc).__name__, exc_info=exc)
        return _response(ErrorCode.INTERNAL, "Something went wrong.", 500)
