"""What the assistant did over a window, from the caller's own audit rows: how often, by which route and model, how
long it took, which tools it chose and which steps were slow. Pure functions over rows already read, so the numbers
can be checked by hand. Latency is the sum of the recorded step times, which is what the clinician waited for."""

import statistics
from collections import Counter, defaultdict
from typing import Any

from medynium_api.features.audit.schemas import AiMetrics, SlowStep

TIMED = {"ASK", "RUN_SAFETY_REVIEW"}
PLAN_STEP = "Choosing what to read"
MIN_RUNS_FOR_SLOW = 2


def _seconds(steps: list[dict[str, Any]]) -> float:
    return sum(float(s.get("ms") or 0) for s in steps) / 1000


def _plan(steps: list[dict[str, Any]]) -> tuple[str | None, list[str]]:
    """The planner model and the tools named in the planning step: 'llama3.1-8b, agent: a + b'."""
    for s in steps:
        if s.get("label") == PLAN_STEP and s.get("detail"):
            model, _, rest = str(s["detail"]).partition(", ")
            tools = (
                [t.strip() for t in rest.split(": ", 1)[1].split(" + ")]
                if ": " in rest and rest.startswith("agent")
                else []
            )
            return model, tools
    return None, []


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(pct / 100 * len(ordered)))], 2)


def summarise(rows: list[dict[str, Any]], days: int) -> AiMetrics:
    routes: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    models: Counter[str] = Counter()
    planners: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    per_step: dict[str, list[float]] = defaultdict(list)
    waits: list[float] = []
    asks = 0
    for r in rows:
        steps = list(r.get("steps") or [])
        if r["action"] == "ASK":
            asks += 1
            routes[r["route"] or "unknown"] += 1
            planner, chosen = _plan(steps)
            if planner:
                planners[planner] += 1
            tools.update(chosen)
        if r["action"] in TIMED:
            waits.append(_seconds(steps))
            for s in steps:
                if s.get("ms") is not None and s.get("label") != PLAN_STEP:
                    per_step[str(s["label"])].append(float(s["ms"]) / 1000)
        outcomes[r["outcome"] or "unknown"] += 1
        if r.get("model"):
            models[r["model"]] += 1
    slow = [
        SlowStep(label=label, runs=len(v), average_seconds=round(statistics.mean(v), 2))
        for label, v in per_step.items()
        if len(v) >= MIN_RUNS_FOR_SLOW
    ]
    slow.sort(key=lambda s: -s.average_seconds)
    return AiMetrics(
        days=days, entries=len(rows), asks=asks, by_route=dict(routes), outcomes=dict(outcomes), models=dict(models),
        planner_models=dict(planners), tools=dict(tools), median_seconds=percentile(waits, 50),
        p95_seconds=percentile(waits, 95), slowest_steps=slow[:5],
        proposals_approved=sum(1 for r in rows if r["action"] == "AGENT_PROPOSED_WRITE"),
        proposals_discarded=sum(1 for r in rows if r["action"] == "AGENT_PROPOSAL_DISCARDED"),
    )  # fmt: skip
