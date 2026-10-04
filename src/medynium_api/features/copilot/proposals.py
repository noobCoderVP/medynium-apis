"""Write proposals (agentic upgrade, phase B2). The assistant never writes: it proposes, the clinician approves a preview.

A proposal holds validated arguments for one write and nothing else. The Approve click calls the same service the
manual screen uses, under the clinician's own session, with the proposal id as the idempotency key. Proposals live in
memory for fifteen minutes: they are a conversation aid, not a record. The record, its history and the audit row are
written by the real write path on approval, so a restart loses only unapproved previews."""

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from medynium_api.core.ids import new_id

TTL_SECONDS = 15 * 60
MAX_OPEN = 200
PROPOSE_KINDS = (
    "add_note",
    "add_allergy",
    "add_diagnosis",
    "add_medication",
    "raise_finding",
    "decide_finding",
)
# Free-text fields must come from the clinician's own words, not from the model's imagination.
GROUNDED_KEYS = {
    "title", "body", "substance", "reaction", "description", "dose_text", "strength_text",
    "reason_description", "reason",
}  # fmt: skip
WORD = re.compile(r"[a-z0-9]{3,}")


def grounded(value: str, question: str) -> bool:
    """At least 60% of the value's words appear in the question (a paraphrase passes, an invention does not)."""
    words = WORD.findall(value.lower())
    if not words:
        return True
    have = set(WORD.findall(question.lower()))
    return sum(1 for w in words if w in have) / len(words) >= 0.6


def clean_args(raw: Any, question: str) -> dict[str, Any] | None:
    """Keep only simple scalar values, drop free text the question does not support. None means malformed."""
    if not isinstance(raw, dict) or len(raw) > 12:
        return None
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or isinstance(value, (dict, list)):
            return None
        if value is None or value == "":
            continue
        if isinstance(value, str):
            if len(value) > 4000:
                return None
            if key in GROUNDED_KEYS and not grounded(value, question):
                continue
        out[key] = value
    return out


@dataclass
class Proposal:
    proposal_id: str
    user_id: str
    patient_id: str
    kind: str
    args: dict[str, Any]
    title: str
    fields: list[tuple[str, str]]
    question: str
    created: float = field(default_factory=time.monotonic)
    status: str = "pending"
    result: dict[str, Any] | None = None

    @property
    def expired(self) -> bool:
        return time.monotonic() - self.created > TTL_SECONDS


class ProposalStore:
    def __init__(self) -> None:
        self._items: dict[str, Proposal] = {}
        self._lock = threading.Lock()

    def add(self, user_id: str, patient_id: str, kind: str, args: dict[str, Any], title: str, fields: list[tuple[str, str]], question: str) -> Proposal:  # fmt: skip
        with self._lock:
            for key in [k for k, p in self._items.items() if p.expired]:
                del self._items[key]
            if len(self._items) >= MAX_OPEN:
                del self._items[next(iter(self._items))]
            proposal = Proposal(
                new_id("PRP", 8), user_id, patient_id, kind, args, title, fields, question
            )
            self._items[proposal.proposal_id] = proposal
            return proposal

    def get(self, proposal_id: str, user_id: str) -> Proposal | None:
        """Own, unexpired proposals only; anyone else's is simply not found."""
        with self._lock:
            found = self._items.get(proposal_id)
            if found is None or found.user_id != user_id or found.expired:
                return None
            return found


store = ProposalStore()
