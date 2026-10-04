"""Part of the composition root: how an approved proposal reaches the real write services (agentic upgrade, B2).

Copilot only knows the proposal kinds. Here each kind is tied to the same pydantic model and the same service the
manual screen uses, so a proposal can never be more than a manual entry would be: same validation, same entitlement
checks, same versioning and history, same audit."""

import datetime as dt
from typing import Any

from pydantic import BaseModel, ValidationError

from medynium_api.core.access import require_patient
from medynium_api.core.config import get_settings
from medynium_api.core.errors import ApiError
from medynium_api.core.session import Session
from medynium_api.features.copilot.ports import ProposalInvalid, ProposalPreview
from medynium_api.features.findings.repository import FindingRepository
from medynium_api.features.findings.rules import check_update, is_open
from medynium_api.features.findings.schemas import FindingCreate, FindingUpdate
from medynium_api.features.findings.service import FindingService
from medynium_api.features.records.schemas import AllergyIn, DiagnosisIn, MedicationIn, NoteIn
from medynium_api.features.records.service import RecordService

# kind -> (records path, model, title, tab where the result appears)
RECORDS: dict[str, tuple[str, type[BaseModel], str, str]] = {
    "add_note": ("notes", NoteIn, "Add a clinical note", "notes"),
    "add_allergy": ("allergies", AllergyIn, "Add an allergy", "overview"),
    "add_diagnosis": ("diagnoses", DiagnosisIn, "Add a diagnosis", "overview"),
    "add_medication": ("medications", MedicationIn, "Add a medicine", "medications"),
}
LABELS = {
    "title": "Title", "body": "Text", "note_type": "Type", "note_date": "Date", "substance": "Substance",
    "reaction": "Reaction", "severity": "Severity", "description": "Description", "onset_date": "Onset",
    "strength_text": "Strength", "dose_text": "Dose", "start_date": "Started", "reason_description": "For",
    "status": "Decision", "is_active": "Active", "reason": "Reason", "follow_up_on": "Follow up on", "assigned_to": "Escalate to",
}  # fmt: skip


def _show(value: Any) -> str:
    return ("Yes" if value else "No") if isinstance(value, bool) else str(value)


def _rows(args: dict[str, Any]) -> list[tuple[str, str]]:
    """Label and value rows for the preview; a flag that is simply the default (an active allergy) is not shown."""
    return [
        (LABELS.get(k, k.replace("_", " ").capitalize()), _show(v))
        for k, v in args.items()
        if not (k == "is_active" and v is True)
    ]


def _problems(exc: ValidationError) -> str:
    parts = [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:3]]
    return (
        "I need a little more to prepare that ("
        + "; ".join(parts)
        + "). Say it again with those details."
    )


class ProposalPorts:
    def preview_proposal(
        self,
        session: Session,
        kind: str,
        patient_id: str,
        args: dict[str, Any],
        last_answer_id: str | None,
    ) -> ProposalPreview:
        try:
            require_patient(session, patient_id)
        except ApiError as exc:
            raise ProposalInvalid("That patient is not available to you.") from exc
        if kind in RECORDS:
            _, model, title, _ = RECORDS[kind]
            try:
                body = model.model_validate(args)
            except ValidationError as exc:
                raise ProposalInvalid(_problems(exc)) from exc
            normal = body.model_dump(mode="json", exclude_none=True)
            return ProposalPreview(title, _rows(normal), normal)
        if kind == "raise_finding":
            return self._preview_raise(session, patient_id, args, last_answer_id)
        return self._preview_decide(session, patient_id, args)

    def _preview_raise(self, session: Session, patient_id: str, args: dict[str, Any], answer_id: str | None) -> ProposalPreview:  # fmt: skip
        consideration = str(args.get("consideration_id") or "")
        if not answer_id or not consideration:
            raise ProposalInvalid(
                "Ask the question first, then tell me which statement to raise as a finding."
            )
        text = FindingRepository().statement(
            session.snowflake_role, patient_id, answer_id, consideration
        )
        if not text:
            raise ProposalInvalid(
                "I couldn't find that statement in the previous answer for this patient."
            )
        return ProposalPreview(
            "Raise a finding",
            [("Statement", text)],
            {"answer_id": answer_id, "consideration_id": consideration},
        )

    def _preview_decide(
        self, session: Session, patient_id: str, args: dict[str, Any]
    ) -> ProposalPreview:
        try:
            body = FindingUpdate.model_validate(args)
        except ValidationError as exc:
            raise ProposalInvalid(_problems(exc)) from exc
        open_ones = [
            f
            for f in FindingService().list_findings(session, patient_id).items
            if is_open(f.status)
        ]
        if len(open_ones) != 1:
            raise ProposalInvalid(
                "There is no open finding on this patient." if not open_ones
                else f"This patient has {len(open_ones)} open findings. Decide on one from the Safety tab."
            )  # fmt: skip
        target = open_ones[0]
        colleagues = frozenset(r["user_id"] for r in FindingRepository().colleagues(patient_id))
        try:
            check_update(target.status, body, session.user_id, dt.date.today(), colleagues)
        except ApiError as exc:
            raise ProposalInvalid(exc.message) from exc
        normal = {
            "finding_id": target.finding_id,
            **body.model_dump(mode="json", exclude_none=True),
        }
        return ProposalPreview("Decide on a finding", [("Finding", target.summary), *_rows(body.model_dump(mode="json", exclude_none=True))], normal)  # fmt: skip

    def execute_proposal(
        self, session: Session, kind: str, patient_id: str, args: dict[str, Any], key: str
    ) -> dict[str, Any]:
        if kind in RECORDS:
            path, model, _, tab = RECORDS[kind]
            written = RecordService(get_settings()).create(
                session, patient_id, path, model.model_validate(args), key
            )
            return {"record_id": written.record_id, "tab": tab}
        if kind == "raise_finding":
            finding = FindingService().create(
                session, patient_id, FindingCreate.model_validate(args)
            )
            return {"record_id": finding.finding_id, "tab": "safety"}
        rest = {k: v for k, v in args.items() if k != "finding_id"}
        finding = FindingService().update(
            session, str(args["finding_id"]), FindingUpdate.model_validate(rest)
        )
        return {"record_id": finding.finding_id, "tab": "safety"}
