"""Which drugs the corpus covers, which it does not, and a way to ask for more (production plan Phase 4).

Nothing here fetches anything: a clinician asks, an admin decides, and an admin adds the label with the setup script
(knowledge/ingest/fetch_openfda.py then extend.py), so the corpus never changes from a request alone and no outside
service is called at run time (NFR-12)."""

from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.config import Settings
from medynium_api.core.errors import conflict, not_found
from medynium_api.core.security.ratelimit import write_limiter
from medynium_api.core.session import Session
from medynium_api.core.snowflake.queries import Row
from medynium_api.features.drug_coverage.repository import DrugCoverageRepository
from medynium_api.features.drug_coverage.schemas import (
    Coverage,
    DrugRequest,
    DrugRequestIn,
    DrugRequestList,
    RequestDecision,
    UnlabelledMedicine,
)

NOTE = (
    "The corpus is built from US (openFDA) labels. A drug with none is listed here as not indexed; it is never answered "
    "from another drug's text. Indian prescribing information would need to be approved as a source before it is added."
)


class DrugCoverageService:
    def __init__(self, settings: Settings, repo: DrugCoverageRepository | None = None) -> None:
        self.settings = settings
        self.repo = repo or DrugCoverageRepository()

    def _items(self, rows: list[Row], with_requester: bool) -> list[DrugRequest]:
        ids = {v for r in rows for v in (r["requested_by"], r["decided_by"]) if v}
        names = self.repo.names(ids)
        return [
            DrugRequest(
                request_id=r["request_id"], drug=r["drug_text"], note=r["note"], status=r["status"],
                requested_at=r["requested_at"], requested_by_name=names.get(r["requested_by"]) if with_requester else None,
                decided_by_name=names.get(r["decided_by"] or ""), decided_at=r["decided_at"], decision_note=r["decision_note"],
            )
            for r in rows
        ]  # fmt: skip

    def request_drug(self, session: Session, body: DrugRequestIn) -> DrugRequest:
        write_limiter.check(session.user_id)
        if body.drug.lower() in self.repo.indexed_names(session.snowflake_role):
            raise conflict(f"{body.drug} is already indexed. Search for it in the knowledge base.")
        existing = self.repo.open_request(session.user_id, body.drug)
        if existing:
            item = self._items([existing], False)[0]
            item.already_open = True
            return item
        row = self.repo.create_request(session.user_id, body.drug, body.note)
        write_audit(
            session,
            AuditEntry(
                action="REQUEST_DRUG", cost_note="no model call", outcome_detail=row["request_id"]
            ),
            strict=True,
        )
        return self._items([row], False)[0]

    def my_requests(self, session: Session) -> DrugRequestList:
        return DrugRequestList(items=self._items(self.repo.requests(None, session.user_id), False))

    def all_requests(self, status: str | None) -> DrugRequestList:
        return DrugRequestList(items=self._items(self.repo.requests(status, None), True))

    def decide(self, admin: Session, request_id: str, body: RequestDecision) -> DrugRequest:
        if self.repo.get(request_id) is None:
            raise not_found()
        if self.repo.decide(request_id, body.status, body.note, admin.user_id) == 0:
            raise conflict("This request has already been decided.")
        write_audit(
            admin,
            AuditEntry(
                action="DECIDE_DRUG_REQUEST",
                cost_note="no model call",
                outcome_detail=f"{request_id}: {body.status}",
            ),
            strict=True,
        )
        row = self.repo.get(request_id)
        assert row is not None
        return self._items([row], True)[0]

    def coverage(self, session: Session) -> Coverage:
        data = self.repo.coverage(session.snowflake_role)
        head, snap = data.head, data.snapshot
        return Coverage(
            snapshot_date=snap.get("snapshot_date"), drugs_known=int(head.get("known") or 0),
            drugs_indexed=int(head.get("indexed") or 0), chunks=int(snap.get("chunk_count") or 0),
            nlem_known=int(head.get("nlem_known") or 0), nlem_indexed=int(head.get("nlem_indexed") or 0),
            not_indexed=data.gaps,
            unlabelled_in_use=[UnlabelledMedicine(medicine=r["medicine"], patients=int(r["patients"])) for r in data.unlabelled],
            open_requests=data.open_requests, note=NOTE,
        )  # fmt: skip
