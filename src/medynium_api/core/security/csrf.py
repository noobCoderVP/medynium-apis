"""Require `X-Medynium-Client: web` on every state-changing request (second defence after SameSite=Lax)."""

import json

from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
HEADER = b"x-medynium-client"
BODY = json.dumps({"error": "forbidden", "message": "Missing or invalid client header."}).encode()


class CsrfMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        if headers.get(HEADER) != b"web":
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(BODY)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": BODY})
            return
        await self.app(scope, receive, send)
