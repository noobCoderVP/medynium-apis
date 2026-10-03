"""Outbound email through Resend (https://resend.com/docs/api-reference/emails/send-email).

Email is a best-effort channel: `send` never raises, it returns whether the message was accepted, and a failure is
logged without the recipient or the body. With no RESEND_API_KEY the mailer only logs that a message was skipped,
so local development and tests need no account.
"""

from dataclasses import dataclass, field
from typing import Protocol

import httpx
import structlog

from medynium_api.core.config import Settings

log = structlog.get_logger()
RESEND_URL = "https://api.resend.com/emails"


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    html: str
    text: str
    kind: str = "general"  # a short label for logs and Resend tags, never the content
    headers: dict[str, str] = field(default_factory=dict)


class Mailer(Protocol):
    def send(self, message: EmailMessage) -> bool: ...


class NoopMailer:
    """Used when email is not configured. Reports the message as not sent."""

    def send(self, message: EmailMessage) -> bool:
        log.info("email_skipped", kind=message.kind, reason="not_configured")
        return False


class ResendMailer:
    def __init__(
        self, api_key: str, sender: str, reply_to: str | None, timeout: float = 10.0
    ) -> None:
        self._api_key = api_key
        self._sender = sender
        self._reply_to = reply_to
        self._timeout = timeout

    def send(self, message: EmailMessage) -> bool:
        payload: dict[str, object] = {
            "from": self._sender,
            "to": [message.to],
            "subject": message.subject,
            "html": message.html,
            "text": message.text,
            "tags": [{"name": "kind", "value": message.kind}],
        }
        if self._reply_to:
            payload["reply_to"] = self._reply_to
        if message.headers:
            payload["headers"] = message.headers
        try:
            response = httpx.post(
                RESEND_URL,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            log.error("email_failed", kind=message.kind, error=type(exc).__name__, status=status)
            return False
        log.info("email_sent", kind=message.kind)
        return True


def get_mailer(settings: Settings) -> Mailer:
    if settings.resend_api_key is None:
        return NoopMailer()
    return ResendMailer(
        settings.resend_api_key.get_secret_value(), settings.email_from, settings.email_reply_to
    )
