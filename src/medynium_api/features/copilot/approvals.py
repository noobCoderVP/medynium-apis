"""Approving or discarding a prepared change. The approval is the only thing that writes (agentic upgrade, B2)."""

from typing import Any

from medynium_api.core.access import require_patient
from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.errors import ApiError, ErrorCode, not_found
from medynium_api.core.session import Session
from medynium_api.features.copilot import proposals
from medynium_api.features.copilot.ports import Ports


class Approvals:
    def __init__(self, ports: Ports) -> None:
        self.ports = ports

    def approve(self, session: Session, proposal_id: str) -> dict[str, Any]:
        if session.role != "DOCTOR":
            raise ApiError(ErrorCode.FORBIDDEN, "Only a doctor can approve a change to the record.")
        proposal = proposals.store.get(proposal_id, session.user_id)
        if proposal is None or proposal.status == "discarded":
            raise not_found()
        if (
            proposal.status == "approved" and proposal.result is not None
        ):  # a second click returns the first result
            return proposal.result
        require_patient(session, proposal.patient_id)
        result = self.ports.execute_proposal(
            session, proposal.kind, proposal.patient_id, proposal.args, proposal.proposal_id
        )
        proposal.status, proposal.result = "approved", {**result, "proposal_id": proposal_id, "patient_id": proposal.patient_id}  # fmt: skip
        write_audit(
            session,
            AuditEntry(
                action="AGENT_PROPOSED_WRITE", via="USER", patient_id=proposal.patient_id, question=proposal.question,
                outcome="OK", outcome_detail=f"{proposal.kind} {proposal_id} -> {result.get('record_id', '')}",
            ),
            strict=True,
        )  # fmt: skip
        return proposal.result

    def discard(self, session: Session, proposal_id: str) -> dict[str, Any]:
        proposal = proposals.store.get(proposal_id, session.user_id)
        if proposal is None or proposal.status == "approved":
            raise not_found()
        proposal.status = "discarded"
        write_audit(
            session,
            AuditEntry(action="AGENT_PROPOSAL_DISCARDED", patient_id=proposal.patient_id, outcome="OK", outcome_detail=f"{proposal.kind} {proposal_id}"),
        )  # fmt: skip
        return {"status": "discarded", "proposal_id": proposal_id}
