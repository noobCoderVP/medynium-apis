"""The assistant's activity summary is plain arithmetic over audit rows."""

from medynium_api.features.audit.metrics import percentile, summarise


def row(action: str, route: str | None, outcome: str, model: str | None, steps: list[dict]) -> dict:
    return {"action": action, "route": route, "outcome": outcome, "model": model, "steps": steps}


PLAN = {
    "label": "Choosing what to read",
    "ms": 2000,
    "detail": "llama3.1-8b, agent: detect_changes + search_labels",
}


def test_counts_routes_models_planners_tools_and_outcomes() -> None:
    rows = [
        row(
            "ASK",
            "agent",
            "OK",
            "claude-sonnet-4-6",
            [PLAN, {"label": "Comparing", "ms": 1000}, {"label": "Writing", "ms": 5000}],
        ),
        row(
            "ASK",
            "lookup",
            "OK",
            None,
            [
                {"label": "Choosing what to read", "ms": 1500, "detail": "llama3.1-8b, lookup"},
                {"label": "Reading", "ms": 500},
            ],
        ),
        row(
            "ASK",
            "refuse",
            "REFUSED",
            None,
            [{"label": "Choosing what to read", "ms": 100, "detail": "rules, no model, refuse"}],
        ),
        row(
            "RUN_SAFETY_REVIEW",
            "safety",
            "OK",
            "claude-sonnet-4-6",
            [{"label": "Drafting", "ms": 20000}],
        ),
        row("AGENT_PROPOSED_WRITE", None, "OK", None, []),
        row("AGENT_PROPOSAL_DISCARDED", None, "OK", None, []),
    ]
    m = summarise(rows, 7)
    assert m.asks == 3 and m.entries == 6
    assert m.by_route == {"agent": 1, "lookup": 1, "refuse": 1}
    assert m.outcomes == {"OK": 5, "REFUSED": 1}
    assert m.models == {"claude-sonnet-4-6": 2}
    assert m.planner_models == {"llama3.1-8b": 2, "rules": 1}
    assert m.tools == {"detect_changes": 1, "search_labels": 1}
    assert (m.proposals_approved, m.proposals_discarded) == (1, 1)


def test_waiting_time_is_the_sum_of_recorded_steps_and_slow_steps_need_two_runs() -> None:
    rows = [
        row(
            "ASK",
            "agent",
            "OK",
            None,
            [{"label": "Writing", "ms": 4000}, {"label": "Reading", "ms": 1000}],
        ),
        row("ASK", "agent", "OK", None, [{"label": "Writing", "ms": 8000}]),
        row("ASK", "lookup", "OK", None, [{"label": "Once", "ms": 9000}]),
    ]
    m = summarise(rows, 7)
    assert m.median_seconds == 8.0 and m.p95_seconds == 9.0
    assert [(s.label, s.runs, s.average_seconds) for s in m.slowest_steps] == [("Writing", 2, 6.0)]


def test_an_empty_window_is_all_zero_not_an_error() -> None:
    m = summarise([], 7)
    assert m.asks == 0 and m.median_seconds is None and m.slowest_steps == [] and m.by_route == {}
    assert percentile([], 50) is None
