"""Outbound email (Resend) and the message templates."""

from medynium_api.core.email.mailer import (
    EmailMessage,
    Mailer,
    NoopMailer,
    ResendMailer,
    get_mailer,
)
from medynium_api.core.email.templates import (
    invite_email,
    otp_email,
    password_changed_email,
    patient_summary_email,
    reset_email,
    welcome_email,
)

__all__ = [
    "EmailMessage",
    "Mailer",
    "NoopMailer",
    "ResendMailer",
    "get_mailer",
    "invite_email",
    "otp_email",
    "password_changed_email",
    "patient_summary_email",
    "reset_email",
    "welcome_email",
]
