"""Error contract from the SRS (section 4.2): {"error": code, "message": text}.

A denied patient must be indistinguishable from a missing one (SEC-05), so `not_found`
always uses the same message and never names the patient.
"""

from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorCode(StrEnum):
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"
    ACTION_NOT_ALLOWED = "action_not_allowed"
    AGENT_UNAVAILABLE = "agent_unavailable"
    TIMEOUT = "timeout"
    # Not in the SRS: used by route stubs until their slice is built, and for bad input.
    NOT_IMPLEMENTED = "not_implemented"
    INVALID_REQUEST = "invalid_request"


class ErrorBody(BaseModel):
    error: ErrorCode
    message: str


NOT_FOUND_MESSAGE = "The requested resource was not found."

_STATUS = {
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.ACTION_NOT_ALLOWED: 403,
    ErrorCode.AGENT_UNAVAILABLE: 503,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.NOT_IMPLEMENTED: 501,
    ErrorCode.INVALID_REQUEST: 422,
}


class ApiError(Exception):
    def __init__(self, code: ErrorCode, message: str | None = None) -> None:
        self.code = code
        self.message = message or (NOT_FOUND_MESSAGE if code is ErrorCode.NOT_FOUND else code.value)
        self.status_code = _STATUS[code]
        super().__init__(self.message)


def not_found() -> ApiError:
    return ApiError(ErrorCode.NOT_FOUND)


def not_implemented(what: str) -> ApiError:
    return ApiError(ErrorCode.NOT_IMPLEMENTED, f"{what} is not implemented yet.")


def _response(code: ErrorCode, message: str, status: int) -> JSONResponse:
    return JSONResponse(ErrorBody(error=code, message=message).model_dump(mode="json"), status)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _response(exc.code, exc.message, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, __: RequestValidationError) -> JSONResponse:
        return _response(ErrorCode.INVALID_REQUEST, "The request was not valid.", 422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _response(ErrorCode.NOT_FOUND, NOT_FOUND_MESSAGE, 404)
        return _response(ErrorCode.INVALID_REQUEST, str(exc.detail), exc.status_code)
