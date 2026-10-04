"""The closed action set (SEC-12, AI-10, AI-11): exactly four actions, each with typed params, enforced here on the
server whatever the router or the prompt said. Each runs under the caller's own session through the same services the
UI uses (SEC-11), so entitlement and audit apply identically. Anything else is `action_not_allowed` and is audited.
The agent never writes to the clinical record and never acts unprompted."""

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from medynium_api.core.access import require_patient
from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.errors import ApiError, ErrorCode, invalid, not_found
from medynium_api.core.session import Session
from medynium_api.core.streaming import Run
from medynium_api.features.copilot.ports import Ports
from medynium_api.features.copilot.safety import SafetyReview

MAX_LISTED = 5


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenPatient(Strict):
    patient_id: str | None = Field(default=None, max_length=20)
    name_query: str | None = Field(default=None, min_length=2, max_length=80)


class ShowTimeline(Strict):
    patient_id: str | None = Field(default=None, max_length=20)
    from_: dt.date | None = Field(default=None, alias="from")
    to: dt.date | None = None
    lab_code: str | None = Field(default=None, max_length=40)


class RunSafetyReview(Strict):
    patient_id: str | None = Field(default=None, max_length=20)


class PinEvidence(Strict):
    patient_id: str | None = Field(default=None, max_length=20)
    answer_id: str = Field(min_length=3, max_length=40)
    evidence_id: str = Field(min_length=1, max_length=20)


ALLOWLIST: dict[str, type[Strict]] = {
    "open_patient": OpenPatient,
    "show_timeline": ShowTimeline,
    "run_safety_review": RunSafetyReview,
    "pin_evidence": PinEvidence,
}
NOT_ALLOWED = (
    "That action is not available. The agent can open a patient, show a timeline or lab trend, "
    "run the safety review, or pin evidence."
)


class Executor:
    def __init__(self, ports: Ports, safety: SafetyReview) -> None:
        self.ports = ports
        self.safety = safety

    def execute(
        self,
        session: Session,
        action: str,
        params: dict[str, Any],
        run: Run,
        *,
        context_patient: str | None = None,
        via: str = "AGENT",
        question: str | None = None,
    ) -> dict[str, Any]:
        model = ALLOWLIST.get(action)
        if model is None:
            write_audit(
                session,
                AuditEntry(action="DENIED_ACTION", via=via, question=question, outcome="ACTION_NOT_ALLOWED", outcome_detail=str(action)[:80]),
                strict=True,
            )  # fmt: skip
            raise ApiError(ErrorCode.ACTION_NOT_ALLOWED, NOT_ALLOWED)
        try:
            parsed = model.model_validate(params)
        except ValidationError as exc:
            raise invalid("The action parameters are not valid.", [{"field": ".".join(map(str, e["loc"])), "problem": e["msg"]} for e in exc.errors()]) from exc  # fmt: skip
        data = parsed.model_dump(by_alias=True)
        patient_id = data.get("patient_id") or context_patient
        if via == "AGENT" and context_patient and action != "open_patient":
            # Text the model read (a note, a pasted line) may name another patient. With a patient open, an
            # agent-planned action stays on that patient; moving elsewhere is the user's own click.
            patient_id = context_patient
        label = {"open_patient": "Opening the patient", "show_timeline": "Preparing the timeline view", "run_safety_review": "Running the safety review", "pin_evidence": "Pinning the evidence"}[action]  # fmt: skip
        result: dict[str, Any]
        with run.step(label) as step:
            if action == "open_patient":
                result = self._open(session, data)
                patient_id = result["patient_id"]
                step.detail = result["name"]
            elif action == "show_timeline":
                patient_id = self._need(patient_id)
                require_patient(session, patient_id)
                view = "lab_trend" if data.get("lab_code") else "timeline"
                result = {
                    "view": view,
                    "patient_id": patient_id,
                    **{k: str(v) for k, v in data.items() if v and k != "patient_id"},
                }
            elif action == "pin_evidence":
                patient_id = self._need(patient_id)
                result = {"pin_id": self.ports.pin_evidence(session, patient_id, data["answer_id"], data["evidence_id"]), "patient_id": patient_id}  # fmt: skip
            else:
                patient_id = self._need(patient_id)
                answer = self.safety.run(
                    session, patient_id, run, question=question or "Run safety review"
                )
                result = {"answer_id": answer.answer_id, "patient_id": patient_id}
        shown = {k: v for k, v in data.items() if v is not None}
        if "patient_id" in shown:
            shown["patient_id"] = patient_id
        run.emit(
            "action",
            {
                "action": action,
                "params": shown,
                "status": "done",
                "result": result,
            },
        )
        if action != "run_safety_review":  # the review writes its own audit row with its evidence
            run.audit_id = write_audit(
                session,
                AuditEntry(action=action.upper(), via=via, patient_id=patient_id, question=question, cost_note="no model call", steps=run.steps),
                strict=True,
            )  # fmt: skip
        return result

    @staticmethod
    def _need(patient_id: str | None) -> str:
        if not patient_id:
            raise invalid("Open a patient first.", [{"field": "patient_id", "problem": "required"}])
        return patient_id

    def _open(self, session: Session, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("patient_id"):
            found = [
                p
                for p in self.ports.find_patients(session, data["patient_id"], 5)
                if p.patient_id == data["patient_id"]
            ]
        elif data.get("name_query"):
            found = self.ports.find_patients(session, data["name_query"], MAX_LISTED + 1)
        else:
            raise invalid(
                "Say which patient to open.", [{"field": "name_query", "problem": "required"}]
            )
        if not found:
            raise not_found()  # denied and missing look the same
        if len(found) > 1:
            listed = [{"patient_id": p.patient_id, "name": p.name, "age": p.age, "sex": p.sex, "detail": p.detail} for p in found[:MAX_LISTED]]  # fmt: skip
            more = "Several patients match. Pick one:" if len(found) <= MAX_LISTED else f"More than {MAX_LISTED} patients match. Use a name or id to narrow it down:"  # fmt: skip
            raise ApiError(ErrorCode.CONFLICT, more, details=listed)
        return {"patient_id": found[0].patient_id, "name": found[0].name}
