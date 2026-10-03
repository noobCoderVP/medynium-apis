"""Speed and cost evidence (Q-7, 07 section 5): time the data screens and each assistant route as a seeded doctor
and record p50 and p95, failures, and the credits used. Calls the live models, so it costs a few credits.

Usage: poetry run python scripts/eval_timing.py [--hero 8] [--runs 20]
Runs at the service layer (no HTTP, no passwords), so network and the UI proxy are not included: add roughly 50 to
100 ms for a request through the API. The first call in the process is reported separately as the cold start.
Writes docs/quality/timing-report.{json,md}.
"""

import argparse
import json
import statistics
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_golden import OUT, execute, make_session  # noqa: E402
from sfadmin import connect  # noqa: E402

from medynium_api.core.config import get_settings  # noqa: E402
from medynium_api.core.errors import ApiError, ErrorCode  # noqa: E402
from medynium_api.features.copilot.routing import decide  # noqa: E402
from medynium_api.features.copilot.service import CopilotService  # noqa: E402
from medynium_api.features.dashboard.service import DashboardService  # noqa: E402
from medynium_api.features.patients.service import PatientService  # noqa: E402
from medynium_api.wiring import build_ports  # noqa: E402

S1 = "P-1042"


def credits_used() -> float | None:
    try:
        conn = connect("MED_ADMIN")
        cur = conn.cursor()
        cur.execute("SHOW RESOURCE MONITORS")
        used = float(cur.fetchall()[0][2])
        conn.close()
        return used
    except Exception:  # noqa: BLE001
        return None


def measure(label: str, runs: int, work: Callable[[], Any], target_s: float) -> dict[str, Any]:
    samples: list[float] = []
    failures = 0
    for _ in range(runs):
        started = time.monotonic()
        try:
            work()
            samples.append(time.monotonic() - started)
        except ApiError:
            failures += 1
    ordered = sorted(samples)

    def pct(q: float) -> float | None:
        return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 2) if ordered else None

    return {
        "label": label, "runs": runs, "failures": failures, "cold_s": round(samples[0], 2) if samples else None,
        "p50_s": round(statistics.median(ordered), 2) if ordered else None, "p95_s": pct(0.95),
        "max_s": round(ordered[-1], 2) if ordered else None, "target_p50_s": target_s,
    }  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--hero", type=int, default=8)
    args = parser.parse_args()
    settings = get_settings()
    session = make_session("sharma@demo.medynium")
    service = CopilotService(settings, build_ports())
    before = credits_used()

    def ask(question: str, screen: str = "patient", patient: str | None = S1) -> Callable[[], Any]:
        def work() -> None:
            out = execute(service, session, {"question": question, "screen": screen}, patient)
            if out["error"]:
                raise ApiError(ErrorCode.INTERNAL)

        return work

    rows = [
        measure("Dashboard data", args.runs, lambda: DashboardService(settings).load(session), 3),
        measure("Patient overview", args.runs, lambda: PatientService(settings).overview(session, S1), 3),
        measure("Router decision only", 10, lambda: decide(settings, "what changed since the last visit?", "patient", S1, []), 2),
        measure("lookup route (current medicines)", args.runs, ask("what are the current medications?"), 1),
        measure("changed route (what changed)", args.runs, ask("what changed since the last visit?"), 1),
        measure("Safety review through the assistant (hero)", args.hero, ask("Is there anything in this patient's medication list worth a second look given the latest results?"), 20),
    ]  # fmt: skip
    after = credits_used()

    OUT.mkdir(parents=True, exist_ok=True)
    spent = round(after - before, 3) if before is not None and after is not None else None
    (OUT / "timing-report.json").write_text(
        json.dumps({"generated": datetime.now(UTC).isoformat(timespec="seconds"), "credits_before": before, "credits_after": after, "credits_spent": spent, "results": rows}, indent=1),
        encoding="utf-8",
    )  # fmt: skip
    lines = [
        "# Timing and cost", "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC at the service layer as the demo doctor (no HTTP, so add roughly 50 to 100 ms through the API).",
        f"Credits: {before} before, {after} after, **{spent} spent by this run**. The resource monitor cap is 100. Snowflake updates the monitor with a delay, so treat this as a lower bound.",
        "Assistant route timings (lookup, changed, hero) include the router call, whose own p50 is the row above. The plan targets are 1 s after routing for cheap routes and 20 s p50 for the hero.", "",
        "| Measure | Runs | Failed | First (cold) s | p50 s | p95 s | Max s | p50 target s | Within target |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]  # fmt: skip
    for r in rows:
        ok = r["p50_s"] is not None and r["p50_s"] <= r["target_p50_s"]
        lines.append(f"| {r['label']} | {r['runs']} | {r['failures']} | {r['cold_s']} | {r['p50_s']} | {r['p95_s']} | {r['max_s']} | {r['target_p50_s']} | {'yes' if ok else '**no**'} |")  # fmt: skip
    (OUT / "timing-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
