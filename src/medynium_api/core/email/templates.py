"""The emails the app sends. Plain HTML with inline styles (mail clients ignore stylesheets) and a text
alternative for every message. Patient details only ever appear in `patient_summary_email`."""

from datetime import datetime
from html import escape

from medynium_api.core.email.mailer import EmailMessage

BRAND = "Medynium"
NOTICE = "Synthetic data for a demonstration. Decision support, not a diagnosis."
_P = 'style="margin:0 0 14px;line-height:1.55"'


def _when(value: datetime | None) -> str:
    return f"{value:%d %b %Y, %H:%M} UTC" if value else "soon"


def _layout(
    title: str,
    paragraphs: list[str],
    *,
    extra: str = "",
    button: tuple[str, str] | None = None,
    big: str | None = None,
    foot: str = "",
) -> str:
    body = "".join(f"<p {_P}>{p}</p>" for p in paragraphs)
    code = (
        '<p style="margin:18px 0;font:700 30px Roboto,Arial,sans-serif;letter-spacing:8px">'
        f"{escape(big)}</p>"
        if big
        else ""
    )
    cta = (
        '<p style="margin:22px 0"><a href="'
        f'{escape(button[1], quote=True)}" style="background:#2f54c8;color:#fff;text-decoration:none;'
        'padding:11px 20px;border-radius:8px;font-weight:600;display:inline-block">'
        f"{escape(button[0])}</a></p>"
        if button
        else ""
    )
    return (
        '<div style="background:#f4f6fb;padding:24px 12px;font-family:Inter,Arial,sans-serif;color:#1c2333">'
        '<div style="max-width:520px;margin:0 auto;background:#fff;border:1px solid #e3e7f1;'
        'border-radius:12px;padding:28px">'
        f'<p style="margin:0 0 18px;font:700 18px Roboto,Arial,sans-serif;color:#2f54c8">{BRAND}</p>'
        f'<h1 style="margin:0 0 14px;font:700 21px Roboto,Arial,sans-serif">{escape(title)}</h1>'
        f"{body}{code}{extra}{cta}"
        '<p style="margin:22px 0 0;font-size:12px;color:#5b6479;line-height:1.5">'
        f"{foot or escape(NOTICE)}</p></div></div>"
    )


def invite_email(
    name: str, role: str, link: str, expires_at: datetime | None, to: str
) -> EmailMessage:
    role_label = "doctor" if role == "DOCTOR" else "assistant"
    when = _when(expires_at)
    html = _layout(
        "Your invitation",
        [
            f"Hello {escape(name)}, you have been invited to {BRAND} as a {role_label}.",
            f"Set your password to activate your account. The link works once and expires {escape(when)}.",
        ],
        button=("Set your password", link),
        foot="If you did not expect this, ignore this email; nothing happens unless the link is used.",
    )
    text = (
        f"Hello {name}, you have been invited to {BRAND} as a {role_label}.\n"
        f"Set your password (one-time link, expires {when}):\n{link}\n"
    )
    return EmailMessage(to, f"You are invited to {BRAND}", html, text, kind="invite")


def reset_email(name: str, link: str, expires_at: datetime | None, to: str) -> EmailMessage:
    when = _when(expires_at)
    html = _layout(
        "Reset your password",
        [
            f"Hello {escape(name)}, use the button below to choose a new password. "
            f"The link works once and expires {escape(when)}.",
            "Your sessions were signed out.",
        ],
        button=("Choose a new password", link),
        foot="If you did not ask for this, tell your administrator. Your password has not changed yet.",
    )
    text = (
        f"Hello {name}, choose a new password (one-time link, expires {when}):\n{link}\n"
        "If you did not ask for this, tell your administrator.\n"
    )
    return EmailMessage(to, f"Reset your {BRAND} password", html, text, kind="password_reset")


def otp_email(name: str, code: str, minutes: int, to: str) -> EmailMessage:
    html = _layout(
        "Your sign-in code",
        [
            f"Hello {escape(name)}, enter this code to finish signing in. It expires in {minutes} minutes."
        ],
        big=code,
        foot="Never share this code. If you did not try to sign in, change your password.",
    )
    text = (
        f"Hello {name}, your {BRAND} sign-in code is {code}. "
        f"It expires in {minutes} minutes. Never share it.\n"
    )
    return EmailMessage(to, f"{code} is your {BRAND} sign-in code", html, text, kind="login_otp")


def welcome_email(name: str, sign_in_url: str, to: str) -> EmailMessage:
    html = _layout(
        f"Welcome to {BRAND}",
        [
            f"Hello {escape(name)}, your account is ready.",
            "Every patient you open and every question you ask is recorded in your activity log.",
        ],
        button=("Sign in", sign_in_url),
    )
    text = f"Hello {name}, your {BRAND} account is ready. Sign in: {sign_in_url}\n"
    return EmailMessage(to, f"Welcome to {BRAND}", html, text, kind="welcome")


def password_changed_email(name: str, to: str) -> EmailMessage:
    html = _layout(
        "Your password was changed",
        [
            f"Hello {escape(name)}, the password for your {BRAND} account was just changed "
            "and your other sessions were signed out."
        ],
        foot="If this was not you, ask your administrator to reset your account now.",
    )
    text = (
        f"Hello {name}, the password for your {BRAND} account was just changed. "
        "If this was not you, ask your administrator to reset it now.\n"
    )
    return EmailMessage(
        to, f"Your {BRAND} password was changed", html, text, kind="password_changed"
    )


def patient_summary_email(
    sender: str,
    to: str,
    patient: str,
    sections: list[tuple[str, list[str]]],
    note: str | None,
    link: str,
) -> EmailMessage:
    """A summary a clinician chose to send. It carries only what the sender could already see, and a link back."""
    blocks: list[str] = []
    lines = [f"{sender} shared a summary for {patient}.", ""]
    if note:
        blocks.append(
            f'<p style="margin:0 0 14px;padding:10px 12px;background:#f4f6fb;border-radius:8px">{escape(note)}</p>'
        )
        lines += [f"Note: {note}", ""]
    for heading, items in sections:
        if not items:
            continue
        li = "".join(f"<li>{escape(i)}</li>" for i in items)
        blocks.append(
            f'<h2 style="margin:16px 0 6px;font:700 15px Roboto,Arial,sans-serif">{escape(heading)}</h2>'
            f'<ul style="margin:0 0 8px;padding-left:20px;line-height:1.55">{li}</ul>'
        )
        lines += [heading, *[f"  - {i}" for i in items], ""]
    html = _layout(
        f"Patient summary: {patient}",
        [f"{escape(sender)} shared this summary with you."],
        extra="".join(blocks),
        button=("Open in Medynium", link),
    )
    text = "\n".join(lines) + f"\nOpen in {BRAND}: {link}\n{NOTICE}\n"
    return EmailMessage(to, f"Patient summary: {patient}", html, text, kind="patient_summary")
