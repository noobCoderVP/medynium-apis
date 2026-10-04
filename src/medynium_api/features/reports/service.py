"""Report upload, review and approval (production plan Phase 2).

An upload is checked here (type from the file's own bytes, size, pages, rate), stored in a private stage, and read in the
background. What was read is staged, never written: a doctor accepts, edits or rejects each row, and approval writes the
accepted rows through the same procedure the forms use, tagged with the report they came from. An assistant may upload and
look; only a doctor decides. A denied patient is audited and answered exactly like a missing one."""

import hashlib
import re
import time
from typing import Any

from medynium_api.core.access import require_patient
from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.config import Settings
from medynium_api.core.errors import ApiError, ErrorCode, conflict, forbidden, invalid, not_found
from medynium_api.core.security.ratelimit import upload_limiter, write_limiter
from medynium_api.core.session import Session
from medynium_api.core.snowflake.queries import Row, json_value
from medynium_api.core.snowflake.timing import pad
from medynium_api.features.reports.jobs import ReportJobs
from medynium_api.features.reports.repository import ReportRepository
from medynium_api.features.reports.review import (
    SUPPORTED_TESTS,
    already_in_record,
    checked_edit,
    clean_name,
    sniff,
)
from medynium_api.features.reports.schemas import (
    ApproveBody,
    ApproveStarted,
    ReportDetail,
    ReportList,
    ReportPage,
    ReportRow,
    ReportSummary,
    RowEdit,
    RowResult,
)


class ReportService:
    def __init__(
        self,
        settings: Settings,
        repo: ReportRepository | None = None,
        jobs: ReportJobs | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo or ReportRepository()
        self.jobs = jobs or ReportJobs(self.repo, settings)

    # Shared steps ---------------------------------------------------------------------------------------------
    def _audit(
        self,
        session: Session,
        action: str,
        patient_id: str | None,
        outcome: str,
        detail: str | None,
    ) -> None:
        write_audit(
            session,
            AuditEntry(action=action, patient_id=patient_id, cost_note="no model call", outcome=outcome, outcome_detail=detail),
            strict=outcome == "OK",
        )  # fmt: skip

    def _guard(self, session: Session, patient_id: str, action: str) -> float:
        started = time.monotonic()
        try:
            require_patient(session, patient_id)
        except ApiError:
            self._audit(session, action, patient_id, "DENIED", None)
            pad(started)
            raise
        return started

    def _fail(
        self, session: Session, result: dict[str, Any], action: str, patient_id: str, started: float
    ) -> ApiError:
        error = result.get("error")
        if error in ("denied", "not_found"):
            self._audit(
                session, action, patient_id, "DENIED" if error == "denied" else "ERROR", str(error)
            )
            pad(started)
            return not_found()
        self._audit(session, action, patient_id, "ERROR", str(error))
        if error == "forbidden":
            return forbidden("Only a doctor can decide on what was read from a report.")
        if error == "conflict":
            return conflict(
                "This row was changed by someone else. Reload the report and try again."
            )
        if error == "identity":
            return ApiError(
                ErrorCode.CONFLICT,
                "The name on this report does not match this patient. Confirm it is theirs to continue.",
                details=[{"field": "confirm_identity", "problem": "name_mismatch"}],
            )
        return invalid(str(result.get("detail") or "That could not be done."))

    # Upload ---------------------------------------------------------------------------------------------------
    def upload(
        self, session: Session, patient_id: str, filename: str, declared: str, data: bytes
    ) -> ReportSummary:
        started = self._guard(session, patient_id, "UPLOAD_REPORT")
        upload_limiter.check(session.user_id)
        if not data:
            raise invalid("The file is empty.")
        if len(data) > self.settings.report_max_bytes:
            raise invalid(
                f"The file is larger than {self.settings.report_max_bytes // (1024 * 1024)} MB."
            )
        kind = sniff(data)
        if kind is None or declared.split(";")[0].strip().lower() not in (
            kind[0],
            "application/octet-stream",
        ):
            raise invalid("Upload a PDF, PNG or JPEG file. The file's content does not match.")
        mime, ext = kind
        if (
            mime == "application/pdf"
            and len(re.findall(rb"/Type\s*/Page[^s]", data)) > self.settings.report_max_pages
        ):
            raise invalid(f"This report has more than {self.settings.report_max_pages} pages.")
        sha = hashlib.sha256(data).hexdigest()
        path = self.repo.put_file(patient_id, sha, ext, data)
        result = self.repo.create_report(
            session.user_id, patient_id, clean_name(filename), mime, len(data), sha, path
        )
        if not result.get("ok"):
            raise self._fail(session, result, "UPLOAD_REPORT", patient_id, started)
        report_id = str(result["report_id"])
        duplicate = bool(result.get("duplicate"))
        if not duplicate:
            self.jobs.submit_process(report_id, session.user_id)
        self._audit(
            session,
            "UPLOAD_REPORT",
            patient_id,
            "OK",
            f"{report_id}{' (duplicate)' if duplicate else ''}",
        )
        row = self.repo.get_report(session.snowflake_role, patient_id, report_id)
        if row is None:
            raise not_found()
        return self._summary(row, {}, duplicate=duplicate)

    # Reads ----------------------------------------------------------------------------------------------------
    def _summary(self, r: Row, names: dict[str, str], duplicate: bool = False) -> ReportSummary:
        return ReportSummary(
            report_id=r["report_id"], patient_id=r["patient_id"], filename=r["filename"], mime_type=r["mime_type"],
            size_bytes=int(r["size_bytes"]), page_count=r["page_count"], status=r["status"], status_detail=r["status_detail"],
            uploaded_at=r["uploaded_at"], uploaded_by_name=names.get(r["uploaded_by"]), extracted_at=r["extracted_at"],
            name_on_report=r["name_on_report"], identity_status=r["identity_status"],
            identity_confirmed=bool(r["identity_confirmed_by"]), rows_kept=r["rows_kept"], rows_dropped=r["rows_dropped"],
            rows_waiting=int(r["rows_waiting"] or 0), duplicate=duplicate,
        )  # fmt: skip

    def list_reports(self, session: Session, patient_id: str) -> ReportList:
        require_patient(session, patient_id)
        rows = self.repo.list_reports(session.snowflake_role, patient_id)
        names = self.repo.names({r["uploaded_by"] for r in rows})
        return ReportList(items=[self._summary(r, names) for r in rows])

    def _flags(self, patient_id: str, role: str, rows: list[Row]) -> dict[str, list[str]]:
        """Extra flags worked out when a person looks: a result or medicine that is already in the record."""
        waiting = [r for r in rows if r["status"] not in ("APPROVED", "REJECTED")]
        labs = (
            self.repo.existing_labs(role, patient_id)
            if any(r["kind"] == "LAB" for r in waiting)
            else []
        )
        listed = (
            self.repo.active_medicines(role, patient_id)
            if any(r["kind"] == "MEDICATION" for r in waiting)
            else []
        )
        return already_in_record(waiting, labs, listed)

    def get_report(self, session: Session, patient_id: str, report_id: str) -> ReportDetail:
        require_patient(session, patient_id)
        role = session.snowflake_role
        head = self.repo.get_report(role, patient_id, report_id)
        if head is None:
            raise not_found()
        rows = self.repo.rows(role, report_id)
        extra = self._flags(patient_id, role, rows)
        names = self.repo.names({head["uploaded_by"]})
        return ReportDetail(
            **self._summary(head, names).model_dump(),
            rows=[
                ReportRow(
                    row_id=r["row_id"], kind=r["kind"], fields=json_value(r["fields"]) or {}, collected_at=r["collected_at"],
                    time_known=bool(r["time_known"]), source_page=int(r["source_page"]), source_quote=r["source_quote"],
                    confidence=float(r["confidence"]), flags=[*(json_value(r["flags"]) or []), *extra.get(r["row_id"], [])],
                    status=r["status"], record_id=r["record_id"], version=int(r["version"]),
                )
                for r in rows
            ],
            pages=[ReportPage(page=int(p["page_no"]), text=p["page_text"]) for p in self.repo.pages(role, report_id)],
        )  # fmt: skip

    def file(self, session: Session, patient_id: str, report_id: str) -> tuple[bytes, str, str]:
        started = self._guard(session, patient_id, "VIEW_REPORT_FILE")
        info = self.repo.file_info(session.snowflake_role, patient_id, report_id)
        if info is None:
            self._audit(session, "VIEW_REPORT_FILE", patient_id, "ERROR", "not_found")
            pad(started)
            raise not_found()
        self._audit(session, "VIEW_REPORT_FILE", patient_id, "OK", report_id)
        return self.repo.get_file(info["stage_path"]), info["mime_type"], info["filename"]

    # Review ---------------------------------------------------------------------------------------------------
    def _decide(
        self,
        session: Session,
        patient_id: str,
        row_id: str,
        decision: str,
        version: int,
        body: RowEdit | None,
    ) -> RowResult:
        write_limiter.check(session.user_id)
        action = f"REPORT_ROW_{decision}"
        started = self._guard(session, patient_id, action)
        row = self.repo.row(session.snowflake_role, patient_id, row_id)
        if row is None:
            self._audit(session, action, patient_id, "ERROR", "not_found")
            pad(started)
            raise not_found()
        fields: dict[str, Any] | None = None
        when: str | None = None
        timed = False
        flags: list[str] = []
        if decision == "EDIT" and body is not None:
            fields, when, timed, flags = checked_edit(row, body)
        if decision == "ACCEPT":
            f = json_value(row["fields"]) or {}
            if row["kind"] == "LAB" and (
                f.get("loinc_code") not in SUPPORTED_TESTS or row["collected_at"] is None
            ):
                raise invalid(
                    "Pick a supported test and give the collection time before accepting."
                )
        result = self.repo.decide_row(
            session.user_id, patient_id, row_id, decision, version, fields, when, timed, flags
        )
        if not result.get("ok"):
            raise self._fail(session, result, action, patient_id, started)
        self._audit(session, action, patient_id, "OK", row_id)
        return RowResult(row_id=row_id, status=result["status"], version=int(result["version"]))

    def edit_row(self, session: Session, patient_id: str, row_id: str, body: RowEdit) -> RowResult:
        return self._decide(session, patient_id, row_id, "EDIT", body.version, body)

    def decide_row(
        self, session: Session, patient_id: str, row_id: str, decision: str, version: int
    ) -> RowResult:
        return self._decide(session, patient_id, row_id, decision, version, None)

    def approve(
        self, session: Session, patient_id: str, report_id: str, body: ApproveBody
    ) -> ApproveStarted:
        write_limiter.check(session.user_id)
        started = self._guard(session, patient_id, "APPROVE_REPORT")
        result = self.repo.begin_approval(
            session.user_id, patient_id, report_id, body.confirm_identity
        )
        if not result.get("ok"):
            raise self._fail(session, result, "APPROVE_REPORT", patient_id, started)
        rows = result.get("rows") or []
        if not rows:
            raise invalid(
                "Nothing is accepted yet. Accept or edit the rows you want added to the record."
            )
        self.jobs.submit_approval(
            report_id, patient_id, session.user_id, rows, self.settings.as_of_iso
        )
        self._audit(session, "APPROVE_REPORT", patient_id, "OK", f"{report_id}: {len(rows)} rows")
        return ApproveStarted(report_id=report_id, queued=len(rows))

    def reject_report(self, session: Session, patient_id: str, report_id: str) -> ReportSummary:
        write_limiter.check(session.user_id)
        started = self._guard(session, patient_id, "REJECT_REPORT")
        result = self.repo.reject_report(session.user_id, patient_id, report_id)
        if not result.get("ok"):
            raise self._fail(session, result, "REJECT_REPORT", patient_id, started)
        self._audit(session, "REJECT_REPORT", patient_id, "OK", report_id)
        head = self.repo.get_report(session.snowflake_role, patient_id, report_id)
        if head is None:
            raise not_found()
        return self._summary(head, {})
