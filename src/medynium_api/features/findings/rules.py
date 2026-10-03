"""What a decision requires. Pure functions, so the rules are tested without a database."""

import datetime as dt

from medynium_api.core.errors import invalid
from medynium_api.features.findings.schemas import FindingUpdate

OPEN = ("NEW", "FLAGGED", "ESCALATED")  # still needs someone to act


def check_update(
    current: str, body: FindingUpdate, caller_id: str, today: dt.date, colleague_ids: frozenset[str]
) -> None:
    """Raise `invalid` unless this decision is complete and allowed from the current status."""
    if body.status == current and body.status != "FLAGGED":
        raise invalid(
            "The finding is already in that state.",
            [{"field": "status", "problem": "unchanged"}],
        )
    problems: list[dict[str, str]] = []
    if body.status == "DISMISSED" and len((body.reason or "").strip()) < 3:
        problems.append({"field": "reason", "problem": "a reason is required to dismiss"})
    if body.status == "FLAGGED" and (body.follow_up_on is None or body.follow_up_on < today):
        problems.append(
            {"field": "follow_up_on", "problem": "a follow-up date today or later is required"}
        )
    if body.status == "ESCALATED":
        if not body.assigned_to:
            problems.append({"field": "assigned_to", "problem": "choose a colleague"})
        elif body.assigned_to == caller_id or body.assigned_to not in colleague_ids:
            problems.append(
                {"field": "assigned_to", "problem": "choose a colleague who has this patient"}
            )
    if problems:
        raise invalid("That decision is incomplete.", problems)


def is_open(status: str) -> bool:
    return status in OPEN
