from typing import Annotated, Literal
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, Request, Response

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.errors import ErrorBody, invalid
from medynium_api.core.session import CurrentSession, DoctorSession
from medynium_api.features.reports.schemas import (
    ApproveBody,
    ApproveStarted,
    ReportDetail,
    ReportList,
    ReportSummary,
    RowDecision,
    RowEdit,
    RowResult,
)
from medynium_api.features.reports.service import ReportService

router = APIRouter(
    tags=["reports"],
    responses={404: {"model": ErrorBody}, 409: {"model": ErrorBody}, 403: {"model": ErrorBody}},
)


def get_service(settings: Annotated[Settings, Depends(get_settings)]) -> ReportService:
    return ReportService(settings)


Service = Annotated[ReportService, Depends(get_service)]


async def read_body(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> bytes:
    """The raw file. The size is checked from the header before the body is read, so an oversize file is never held."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.report_max_bytes:
        raise invalid(f"The file is larger than {settings.report_max_bytes // (1024 * 1024)} MB.")
    return await request.body()


Body = Annotated[bytes, Depends(read_body)]


@router.post("/patients/{patient_id}/reports", status_code=202)
def upload_report(
    patient_id: str,
    request: Request,
    session: CurrentSession,
    service: Service,
    body: Body,
    filename: Annotated[str, Header(alias="X-Filename", min_length=1, max_length=200)],
) -> ReportSummary:
    """Upload a PDF, PNG or JPEG report as the raw request body (set `X-Filename`). It is read in the background: what
    is read is staged for a doctor, never written to the record. The same file twice returns the first upload."""
    return service.upload(
        session, patient_id, unquote(filename), request.headers.get("content-type", ""), body
    )


@router.get("/patients/{patient_id}/reports")
def list_reports(patient_id: str, session: CurrentSession, service: Service) -> ReportList:
    return service.list_reports(session, patient_id)


@router.get("/patients/{patient_id}/reports/{report_id}")
def get_report(
    patient_id: str, report_id: str, session: CurrentSession, service: Service
) -> ReportDetail:
    """The report, the rows read from it (each with the exact words and page it came from) and the page text."""
    return service.get_report(session, patient_id, report_id)


@router.get("/patients/{patient_id}/reports/{report_id}/file", response_class=Response)
def report_file(
    patient_id: str, report_id: str, session: CurrentSession, service: Service
) -> Response:
    """The original file, streamed after an entitlement check. No link to it is ever handed out."""
    data, mime, name = service.file(session, patient_id, report_id)
    return Response(
        data,
        media_type=mime,
        headers={
            "Content-Disposition": f'inline; filename="{name}"',
            "Cache-Control": "no-store",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.put("/patients/{patient_id}/reports/rows/{row_id}")
def edit_row(
    patient_id: str, row_id: str, body: RowEdit, session: DoctorSession, service: Service
) -> RowResult:
    """Correct what was read from a report row. A lab needs a supported test and a collection time."""
    return service.edit_row(session, patient_id, row_id, body)


@router.post("/patients/{patient_id}/reports/rows/{row_id}/{decision}")
def decide_row(
    patient_id: str,
    row_id: str,
    decision: Literal["accept", "reject", "reset"],
    body: RowDecision,
    session: DoctorSession,
    service: Service,
) -> RowResult:
    """Accept or reject one row, or put it back to waiting. Only a doctor decides; nothing is written until approval."""
    return service.decide_row(session, patient_id, row_id, decision.upper(), body.version)


@router.post("/patients/{patient_id}/reports/{report_id}/approve", status_code=202)
def approve_report(
    patient_id: str, report_id: str, body: ApproveBody, session: DoctorSession, service: Service
) -> ApproveStarted:
    """Write the accepted and edited rows to the record, each tagged with this report as its source. A report whose
    printed name does not match the patient needs `confirm_identity`."""
    return service.approve(session, patient_id, report_id, body)


@router.post("/patients/{patient_id}/reports/{report_id}/reject")
def reject_report(
    patient_id: str, report_id: str, session: DoctorSession, service: Service
) -> ReportSummary:
    """Reject the whole report: nothing from it is written."""
    return service.reject_report(session, patient_id, report_id)
