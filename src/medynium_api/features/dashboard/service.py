"""Dashboard: three widgets from precomputed tables, no AI call (FR-17)."""

from datetime import date
from typing import Any

from medynium_api.core.config import Settings
from medynium_api.core.schemas import KIND_LABELS, EncounterRef, Money, flags_from
from medynium_api.core.session import Session
from medynium_api.features.dashboard.repository import DashboardRepository
from medynium_api.features.dashboard.schemas import (
    BriefingItem,
    BriefingResponse,
    DashboardResponse,
    LabChange,
    MedicationChange,
    RecentChanges,
    UtilizationSummary,
    WorklistItem,
)


class DashboardService:
    def __init__(self, settings: Settings, repo: DashboardRepository | None = None) -> None:
        self.settings = settings
        self.repo = repo or DashboardRepository()

    def load(self, session: Session) -> DashboardResponse:
        as_of = self.settings.as_of_iso
        data: Any = self.repo.load(session.snowflake_role, as_of)
        worklist = [
            WorklistItem(
                patient_id=r["patient_id"],
                name=r["full_name"],
                age=int(r["age_years"]),
                sex=r["sex"],
                last_encounter=EncounterRef(
                    date=r["last_encounter_date"],
                    kind=r["last_encounter_kind"],
                    label=KIND_LABELS.get(
                        r["last_encounter_kind"] or "", r["last_encounter_label"]
                    ),
                ),
                flags=flags_from(
                    int(r["new_lab_count"] or 0),
                    bool(r["has_new_medication_change"]),
                    bool(r["has_recent_emergency"]),
                    bool(r["has_new_document"]),
                    r["last_encounter_date"] if r["last_encounter_kind"] == "EMERGENCY" else None,
                ),
            )
            for r in data["worklist"]
        ]
        labs = [
            LabChange(
                patient_id=r["patient_id"], name=r["full_name"], test=r["short_name"],
                latest=float(r["latest_value"]),
                previous=float(r["previous_value"]) if r["previous_value"] is not None else None,
                unit=r["unit"], date=r["d"], abnormal=r["abnormal_flag"] if r["abnormal_flag"] != "NORMAL" else None,
            )
            for r in data["labs"]
        ]  # fmt: skip
        meds = [
            MedicationChange(
                patient_id=r["patient_id"], name=r["full_name"], drug=r["drug_name"],
                change=r["change_note"] or "Started",
                date=r["last_change_date"] or r["start_date"],
            )
            for r in data["meds"]
        ]  # fmt: skip
        u = data["utilization"]
        return DashboardResponse(
            as_of=date.fromisoformat(as_of),
            worklist=worklist,
            recent_changes=RecentChanges(labs=labs, medications=meds),
            utilization=UtilizationSummary(
                patients=int(u.get("patients", 0)), opd_visits=int(u.get("opd", 0)),
                emergency_visits=int(u.get("ed", 0)), hospitalizations=int(u.get("hosp", 0)),
                procedures=int(u.get("proc", 0)), approved=Money(amount=float(u.get("approved", 0))),
            ),
        )  # fmt: skip

    def briefing(self, session: Session) -> BriefingResponse:
        """On-request briefing (A-13): one line per change, built from the caller's own dashboard data."""
        data = self.load(session)
        items = [
            BriefingItem(
                patient_id=c.patient_id, name=c.name,
                text=f"{c.test} {c.latest:g} {c.unit or ''} on {c.date:%d %b %Y}"
                + (f" (previous {c.previous:g})" if c.previous is not None else "")
                + (f", flagged {c.abnormal.lower()}" if c.abnormal else ""),
            )
            for c in data.recent_changes.labs
        ] + [
            BriefingItem(
                patient_id=m.patient_id, name=m.name,
                text=f"{m.drug}: {m.change} on {m.date:%d %b %Y}",
            )
            for m in data.recent_changes.medications
        ]  # fmt: skip
        return BriefingResponse(
            as_of=data.as_of,
            items=items,
            empty_note=None if items else "No recent lab or medication changes for your patients.",
        )
