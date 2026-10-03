"""Emailing a patient summary (a clinician's choice, one recipient, always audited).

The summary is built from the same entitled overview the caller can already open, so an email can never carry
more than the sender could see. The audit row records that a summary left, for which patient and which sections,
and never the recipient address or the body.
"""

from collections.abc import Sequence

from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.config import Settings
from medynium_api.core.email import Mailer, get_mailer, patient_summary_email
from medynium_api.core.errors import ApiError, ErrorCode
from medynium_api.core.security.ratelimit import RateLimiter
from medynium_api.core.session import Session
from medynium_api.features.patients.repository import PatientRepository
from medynium_api.features.patients.schemas import Overview, ShareRequest, ShareResult

share_limiter = RateLimiter(limit=10, window_seconds=60)


def _sections(overview: Overview, include: Sequence[str]) -> list[tuple[str, list[str]]]:
    out: list[tuple[str, list[str]]] = [
        (
            "Patient",
            [
                f"{overview.name}, {overview.age}, {overview.sex}"
                + (f", {overview.city}" if overview.city else "")
            ],
        )
    ]
    if "diagnoses" in include:
        out.append(("Active diagnoses", [d.description for d in overview.diagnoses]))
    if "medications" in include:
        out.append(
            (
                "Current medications",
                [
                    " ".join(filter(None, [m.drug, m.dose or m.strength]))
                    for m in overview.medications
                ],
            )
        )
    if "labs" in include:
        abnormal = [lab for lab in overview.latest_labs if lab.flag in ("LOW", "HIGH")]
        out.append(
            (
                "Abnormal labs",
                [
                    f"{lab.test} {lab.value:g} {lab.unit or ''} ({lab.flag}, {lab.date:%d %b %Y})".replace(
                        "  ", " "
                    )
                    for lab in abnormal
                ],
            )
        )
    if "events" in include:
        out.append(
            ("Recent events", [f"{e.date:%d %b %Y}: {e.title}" for e in overview.recent_events])
        )
    return out


class SharingService:
    def __init__(
        self,
        settings: Settings,
        repo: PatientRepository | None = None,
        mailer: Mailer | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo or PatientRepository()
        self.mailer = mailer or get_mailer(settings)

    def send(self, session: Session, overview: Overview, body: ShareRequest) -> ShareResult:
        """`overview` was loaded through the entitlement gate, so reaching this point means access was granted."""
        share_limiter.check(f"share:{session.user_id}")
        sender = self.repo.sender_name(session.user_id) or "A Medynium clinician"
        link = f"{self.settings.public_app_url.rstrip('/')}/patients/{overview.patient_id}"
        message = patient_summary_email(
            sender, body.to, overview.name, _sections(overview, body.include), body.note, link
        )
        sent = self.mailer.send(message)
        write_audit(
            session,
            AuditEntry(
                action="EMAIL_SUMMARY",
                outcome="OK" if sent else "ERROR",
                patient_id=overview.patient_id,
                outcome_detail=f"sections={','.join(body.include)}",
            ),
        )
        if not sent:
            raise ApiError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "The email could not be sent. Check the email settings.",
            )
        return ShareResult(sent=True)
