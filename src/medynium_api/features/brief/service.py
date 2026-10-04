"""Attention, changes, gaps and the brief for one patient. Entitlement first (a denied patient is audited and answered
like a missing one), then the shared rules in core/intel under the caller's role. No model call except the optional
written summary, which is checked against the rule signals before it is shown."""

import datetime as dt
import time

from medynium_api.core.access import require_patient
from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.config import Settings
from medynium_api.core.errors import ApiError, invalid, not_found
from medynium_api.core.intel import data, doctors, profile, rules
from medynium_api.core.intel.models import AttentionItem, ChangeSet, GapItem
from medynium_api.core.security.ratelimit import ask_limiter
from medynium_api.core.session import Session
from medynium_api.core.snowflake.timing import pad
from medynium_api.features.brief import summary, written
from medynium_api.features.brief.schemas import (
    AttentionResponse,
    BriefResponse,
    GapResponse,
    LatestResult,
    PatientSummary,
    SummaryResponse,
)

MAX_GAPS_IN_BRIEF = 4


def _counts(items: list[AttentionItem]) -> dict[str, int]:
    return {s: sum(1 for i in items if i.severity == s) for s in ("high", "moderate", "info")}


def headline(snap: data.Snapshot, items: list[AttentionItem], changes: ChangeSet) -> str:
    """The rule-made one-paragraph brief. Also the fallback for the written summary."""
    h = snap.head
    who = f"{h['age_years']}-year-old {'man' if h['sex'] == 'M' else 'woman'}"
    dx = ", ".join(snap.diagnoses[:3])
    first = f"{who} with {dx}." if dx else f"{who}."
    if items:
        top = "; ".join(i.title for i in items[:3])
        second = f"{len(items)} thing{'s' if len(items) != 1 else ''} may need attention: {top}."
    else:
        second = "Nothing stands out for attention in the record."
    third = f"{len(changes.items)} change{'s' if len(changes.items) != 1 else ''} {changes.label}."
    return f"{first} {second} {third}"


def _signals(
    snap: data.Snapshot, items: list[AttentionItem], changes: ChangeSet, gaps: list[GapItem]
) -> str:
    h = snap.head
    lines = [
        f"Patient: {h['age_years']} years, {'male' if h['sex'] == 'M' else 'female'}.",
        f"Diagnoses: {', '.join(snap.diagnoses) or 'none listed'}.",
    ]
    lines += [
        f"Attention ({i.severity}): {i.title}" + (f" - {i.detail}" if i.detail else "")
        for i in items
    ]
    lines.append(f"Changes {changes.label}: {changes.counts or 'none'}")
    lines += [f"Change: {c.title}" for c in changes.items[:6]]
    lines += [f"Missing: {g.title}" for g in gaps[:MAX_GAPS_IN_BRIEF]]
    return "\n".join(lines)


class BriefService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _snap(self, session: Session, patient_id: str, what: str) -> data.Snapshot:
        started = time.monotonic()
        try:
            require_patient(session, patient_id)
            snap = data.snapshot(session.snowflake_role, patient_id)
            if snap is None:
                raise not_found()
            return snap
        except ApiError:
            write_audit(
                session,
                AuditEntry(
                    action=what, patient_id=patient_id, outcome="DENIED", cost_note="no model call"
                ),
            )
            pad(started)
            raise

    def attention(self, session: Session, patient_id: str) -> AttentionResponse:
        snap = self._snap(session, patient_id, "PATIENT_ATTENTION")
        items = data.attention_items(session.snowflake_role, patient_id, snap) or []
        return AttentionResponse(
            patient_id=patient_id, as_of=snap.as_of, items=items, counts=_counts(items)
        )

    def changes(self, session: Session, patient_id: str, choice: str) -> ChangeSet:
        snap = self._snap(session, patient_id, "PATIENT_CHANGES")
        try:
            result = data.change_set(session.snowflake_role, patient_id, choice, snap)
        except ValueError as exc:
            raise invalid(str(exc)) from exc
        assert result is not None
        return result

    def gaps(self, session: Session, patient_id: str) -> GapResponse:
        snap = self._snap(session, patient_id, "PATIENT_GAPS")
        return GapResponse(
            patient_id=patient_id,
            items=data.gap_items(session.snowflake_role, patient_id, snap) or [],
        )

    def _parts(
        self, session: Session, patient_id: str, action: str
    ) -> tuple[data.Snapshot, list[AttentionItem], ChangeSet, list[GapItem]]:
        snap = self._snap(session, patient_id, action)
        role = session.snowflake_role
        items = data.attention_items(role, patient_id, snap) or []
        changes = data.change_set(role, patient_id, "previous_visit", snap)
        assert changes is not None
        return snap, items, changes, data.gap_items(role, patient_id, snap) or []

    def brief(self, session: Session, patient_id: str) -> BriefResponse:
        snap, items, changes, gaps = self._parts(session, patient_id, "PATIENT_BRIEF")
        h = snap.head
        flagged_first = sorted(
            snap.labs,
            key=lambda x: (
                x.get("abnormal_flag") not in ("LOW", "HIGH"),
                -(rules.day(x["latest_at"]) or dt.date.min).toordinal(),
            ),
        )
        results = [
            LatestResult(
                name=lab["short_name"],
                value=rules.fmt(lab["latest_value"]),
                unit=lab.get("unit"),
                flag=lab["abnormal_flag"] if lab.get("abnormal_flag") in ("LOW", "HIGH") else None,
                date=rules.day(lab["latest_at"]),
                previous=None
                if lab.get("previous_value") is None
                else rules.fmt(lab["previous_value"]),
                source=rules.lab_ref(lab),
            )
            for lab in flagged_first[:8]
        ]
        write_audit(
            session,
            AuditEntry(
                action="PATIENT_BRIEF",
                patient_id=patient_id,
                outcome="OK",
                cost_note="no model call",
            ),
        )
        return BriefResponse(
            patient_id=patient_id,
            name=h["full_name"],
            age=int(h["age_years"]),
            sex=h["sex"],
            as_of=snap.as_of,
            headline=headline(snap, items, changes),
            attention=AttentionResponse(
                patient_id=patient_id, as_of=snap.as_of, items=items, counts=_counts(items)
            ),
            changes=changes,
            gaps=gaps[:MAX_GAPS_IN_BRIEF],
            latest_results=results,
        )

    def summary(self, session: Session, patient_id: str) -> SummaryResponse:
        snap, items, changes, gaps = self._parts(session, patient_id, "PATIENT_BRIEF_SUMMARY")
        result = summary.summarise(
            self.settings,
            patient_id,
            _signals(snap, items, changes, gaps),
            headline(snap, items, changes),
        )
        note = (
            "written summary checked against the rule signals"
            if result.source == "model"
            else "rule-made, no model call"
        )
        write_audit(
            session,
            AuditEntry(
                action="PATIENT_BRIEF_SUMMARY",
                patient_id=patient_id,
                outcome="OK",
                model=result.model,
                cost_note=note,
            ),
        )
        return result

    # The stored written summary ---------------------------------------------------------------------------------------
    def written_summary(self, session: Session, patient_id: str) -> PatientSummary:
        self._snap(
            session, patient_id, "PATIENT_SUMMARY"
        )  # entitlement first; a denied patient is audited like a missing one
        row = written.load(session.snowflake_role, patient_id)
        if row is None:
            return PatientSummary(patient_id=patient_id, exists=False)
        by = doctors.title(name) if (name := self._name(row["generated_by"])) else None
        return PatientSummary(
            patient_id=patient_id, exists=True, markdown=row["summary_md"], source=row["source"], model=row["model"],
            generated_at=row["generated_at"], generated_by=by,
            changed_since=written.changed_since(session.snowflake_role, patient_id, row["generated_at"]),
        )  # fmt: skip

    def refresh_written_summary(self, session: Session, patient_id: str) -> PatientSummary:
        """Write the summary again from the record as it is now and replace the stored one."""
        ask_limiter.check(session.user_id)
        self._snap(session, patient_id, "PATIENT_SUMMARY_REFRESH")
        facts = profile.gather(session.snowflake_role, patient_id)
        if facts is None:
            raise not_found()
        result = written.write(self.settings, facts)
        written.save(session.snowflake_role, session.user_id, facts, result)
        write_audit(
            session,
            AuditEntry(
                action="PATIENT_SUMMARY_REFRESH", patient_id=patient_id, outcome="OK", model=result.model,
                cost_note="written from the record and checked against it" if result.source == "model" else "rule-made, no model call",
            ),
        )  # fmt: skip
        return self.written_summary(session, patient_id)

    @staticmethod
    def _name(user_id: str | None) -> str | None:
        return doctors._names([user_id]).get(user_id) if user_id else None
