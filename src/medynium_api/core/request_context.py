"""Request id, timing and response hygiene as a pure ASGI middleware (safe for SSE streams).

Logs method, route template (never the raw path with ids), status, duration and the caller's user id (warning for 4xx, error for 5xx). Never logs bodies, cookies,
tokens, patient names or question text.
"""

import time

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from medynium_api.core.ids import request_id

log = structlog.get_logger()
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = request_id()
        started = time.perf_counter()
        status = 500
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)
        private = scope["path"] not in PUBLIC_PATHS

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", rid.encode()))
                headers.append((b"x-content-type-options", b"nosniff"))
                if private:
                    headers.append((b"cache-control", b"private, no-store"))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            emit = log.error if status >= 500 else log.warning if status >= 400 else log.info
            emit(
                "request",
                method=scope["method"],
                route=getattr(route, "path", "unmatched"),
                status=status,
                ms=round((time.perf_counter() - started) * 1000),
                user_id=scope.get("state", {}).get("user_id"),
            )
            structlog.contextvars.clear_contextvars()
