"""The report pipeline, run in the background so an upload returns at once (production plan Phase 2).

process: parse the pages in Snowflake, ask a model to read each page, keep only what extraction.py can verify against the
page text, stage the survivors for a doctor. write_approved: write each approved row through the same procedure the
forms use. Every state lives in the REPORT table, so a restart loses nothing: the sweeper re-runs reports stuck before
extraction, at most three times. The model sees one page of text and nothing else; it has no tools and its reply is only
ever data to validate."""

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog

from medynium_api.core.config import Settings, get_settings
from medynium_api.core.cortex.complete import complete
from medynium_api.core.errors import ApiError
from medynium_api.core.ids import role_for_user
from medynium_api.features.reports import extraction
from medynium_api.features.reports.repository import ReportRepository

log = structlog.get_logger()
PROMPT = (__import__("pathlib").Path(__file__).parent / "prompts" / "extract.md").read_text(
    encoding="utf-8"
)
SWEEP_SECONDS = 60
STUCK_AFTER_SECONDS = 120
ENTITY = {"LAB": "LAB_RESULT", "MEDICATION": "MEDICATION", "DIAGNOSIS": "DIAGNOSIS"}


def record_payload(kind: str, fields: dict[str, Any], collected_at: str | None) -> dict[str, Any]:
    """An approved row as the form payload the write procedure expects."""
    if kind == "LAB":
        return {
            "loinc_code": fields["loinc_code"],
            "value_num": fields["value_num"],
            "observed_at": collected_at,
        }
    if kind == "MEDICATION":
        keys = ("description", "strength_text", "dose_text", "start_date", "stop_date")
        return {k: fields.get(k) for k in keys if fields.get(k)}
    return {k: fields.get(k) for k in ("description", "onset_date") if fields.get(k)}


class ReportJobs:
    def __init__(
        self, repo: ReportRepository | None = None, settings: Settings | None = None
    ) -> None:
        self.repo = repo or ReportRepository()
        self.settings = settings or get_settings()
        self._pool: ThreadPoolExecutor | None = None
        self._sweeper: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def _ensure(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="reports")
            if self._sweeper is None or not self._sweeper.is_alive():
                self._stop.clear()
                self._sweeper = threading.Thread(
                    target=self._sweep, name="reports-sweeper", daemon=True
                )
                self._sweeper.start()
            return self._pool

    def submit_process(self, report_id: str, actor_id: str) -> None:
        self._ensure().submit(self.process, report_id, actor_id)

    def submit_approval(
        self, report_id: str, patient_id: str, actor_id: str, rows: list[dict[str, Any]], as_of: str
    ) -> None:
        self._ensure().submit(self.write_approved, report_id, patient_id, actor_id, rows, as_of)

    def stop(self) -> None:
        self._stop.set()

    def _sweep(self) -> None:
        while not self._stop.wait(SWEEP_SECONDS):
            try:
                for report_id, uploader in self.repo.stuck_reports(STUCK_AFTER_SECONDS):
                    log.warning("report_stuck_retry", report_id=report_id)
                    self._ensure().submit(self.process, report_id, uploader)
            except Exception as exc:
                log.error("report_sweep_failed", error=type(exc).__name__)

    # Reading ---------------------------------------------------------------------------------------------------
    def _read_page(self, number: int, total: int, text: str) -> dict[str, Any] | None:
        user = f'Page {number} of {total}. Page text between the markers:\n"""\n{text[:12000]}\n"""'
        messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": user}]
        for _ in range(2):  # one repair attempt on a malformed reply
            completion = complete(self.settings.extract_model, messages, max_tokens=1800)
            try:
                return extraction.parse_model_json(completion.text)
            except ValueError as exc:
                log.warning("report_page_json_invalid", page=number, reason=str(exc)[:60])
                messages += [
                    {"role": "assistant", "content": completion.text},
                    {
                        "role": "user",
                        "content": "That was not valid JSON. Reply with ONLY the JSON object.",
                    },
                ]
        return None

    def process(self, report_id: str, actor_id: str | None) -> None:
        try:
            parsed = self.repo.parse_report(report_id, self.settings.report_max_pages)
            if not parsed.get("ok"):
                log.info("report_parse_stopped", report_id=report_id, reason=parsed.get("error"))
                return
            pack = self.repo.report_pages(report_id)
            patient_id = str(pack["patient_id"])
            pages: list[dict[str, Any]] = pack.get("pages") or []
            role = role_for_user(actor_id) if actor_id else None
            known = self.repo.known_drug_names(role) if role else set()
            result = extraction.Extraction()
            unreadable = 0
            for page in pages:
                reply = self._read_page(int(page["page"]), len(pages), str(page["text"]))
                if reply is None:
                    unreadable += 1
                    continue
                extraction.keep_rows(int(page["page"]), str(page["text"]), reply, result, known)
            if unreadable == len(pages):
                self.repo.fail_report(
                    report_id,
                    "The reading model did not give a usable answer. Upload the file again.",
                )
                return
            status = extraction.identity(
                result.name_on_report,
                result.report_patient_id,
                str(pack["patient_name"]),
                patient_id,
            )
            notes = []
            if result.injection_seen:
                notes.append("Text on the page that tried to instruct the assistant was ignored.")
            if unreadable:
                notes.append(f"{unreadable} page(s) could not be read.")
            meta = {
                "name": result.name_on_report, "identity": status, "model": self.settings.extract_model,
                "dropped": result.dropped, "note": " ".join(notes) or None,
            }  # fmt: skip
            self.repo.stage_rows(report_id, result.rows, meta)
            log.info(
                "report_extracted",
                report_id=report_id,
                rows=len(result.rows),
                dropped=result.dropped,
                identity=status,
            )
        except ApiError as exc:
            log.warning("report_model_unavailable", report_id=report_id, code=exc.code.value)
            self.repo.fail_report(
                report_id, "The reading model was unavailable. Upload the file again to retry."
            )
        except Exception as exc:
            log.error("report_process_failed", report_id=report_id, error=type(exc).__name__)
            try:
                self.repo.fail_report(report_id, "This report could not be read.")
            except Exception:
                log.error("report_fail_mark_failed", report_id=report_id)

    # Writing approved rows -------------------------------------------------------------------------------------
    def write_approved(
        self, report_id: str, patient_id: str, actor_id: str, rows: list[dict[str, Any]], as_of: str
    ) -> None:
        results: list[dict[str, str]] = []
        for row in rows:
            try:
                out = self.repo.write_record(
                    actor_id, ENTITY[row["kind"]], patient_id,
                    record_payload(row["kind"], row["fields"], row.get("collected_at")),
                    f"rpt-{row['row_id']}", f"REPORT:{report_id}", as_of,
                )  # fmt: skip
            except Exception as exc:
                log.error("report_row_write_failed", row_id=row["row_id"], error=type(exc).__name__)
                continue
            if out.get("ok"):
                results.append({"row_id": row["row_id"], "record_id": str(out["record_id"])})
            else:
                log.warning(
                    "report_row_refused",
                    row_id=row["row_id"],
                    error=out.get("error"),
                    detail=out.get("detail"),
                )
        try:
            self.repo.finish_report(actor_id, patient_id, report_id, results)
        except Exception as exc:
            log.error("report_finish_failed", report_id=report_id, error=type(exc).__name__)
        log.info("report_approved", report_id=report_id, written=len(results), asked=len(rows))
