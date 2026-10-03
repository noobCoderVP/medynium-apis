from fastapi import APIRouter

from medynium_api.core.errors import ErrorBody, not_found
from medynium_api.core.evidence.store import load_evidence
from medynium_api.core.session import CurrentSession
from medynium_api.features.evidence.schemas import EvidenceResponse

router = APIRouter(tags=["evidence"], responses={404: {"model": ErrorBody}})


@router.get("/evidence/{answer_id}")
def get_evidence(answer_id: str, session: CurrentSession) -> EvidenceResponse:
    """The Why? panel: patient records, the SQL that ran and source sections. Only the asker, and only while still
    entitled to the patient, can read an answer's evidence; anything else is the standard not found."""
    evidence = load_evidence(session, answer_id)
    if evidence is None:
        raise not_found()
    return evidence
