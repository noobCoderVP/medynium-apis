"""Latest golden-run results for the admin screen. Runs are started with scripts/eval_golden.py --store; this
feature only reads them, so no model is called and nothing is re-run from a request."""

from medynium_api.core.session import Session
from medynium_api.features.quality.repository import QualityRepository
from medynium_api.features.quality.schemas import GoldenCase, GoldenRun, GoldenRunList


class QualityService:
    def __init__(self, repo: QualityRepository | None = None) -> None:
        self.repo = repo or QualityRepository()

    def golden_runs(self, admin: Session, limit: int = 10) -> GoldenRunList:
        rows = self.repo.runs(admin.snowflake_role, limit)
        runs = [
            GoldenRun(
                run_id=r["run_id"], started_at=r["started_at"], finished_at=r["finished_at"],
                status=r["status"], total=int(r["golden_total"] or 0), passed=int(r["golden_passed"] or 0), cases=[],
            )
            for r in rows
        ]  # fmt: skip
        if runs:
            runs[0].cases = [
                GoldenCase(
                    seq=int(c["seq"]), group=c["set_name"], question=c["question"], result=c["result"],
                    route=c["route_actual"], detail=None if c["result"] == "PASS" else c["expected"],
                )
                for c in self.repo.results(admin.snowflake_role, runs[0].run_id)
            ]  # fmt: skip
        return GoldenRunList(latest=runs[0] if runs else None, history=runs[1:])
