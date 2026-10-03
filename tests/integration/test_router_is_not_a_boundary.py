"""Q-S4: the router is not a security boundary (AGENTS rule 4). Force it to be wrong, as a confused or manipulated
model might be, and show the server's own checks still hold: entitlement, the closed action list and the audit."""

import pytest
from fastapi.testclient import TestClient

from medynium_api.core.security.ratelimit import ask_limiter
from medynium_api.features.copilot import routing
from medynium_api.features.copilot.routing import Step
from tests.integration.test_dashboard import signed_in

pytestmark = pytest.mark.snowflake
S3 = "P-1093"
NOT_FOUND = {"error": "not_found", "message": "The requested resource was not found."}
JSON = {"Accept": "application/json"}


def force(monkeypatch: pytest.MonkeyPatch, *steps: Step) -> None:
    """Make the router answer with these steps whatever it is asked."""
    monkeypatch.setattr(routing, "call_router", lambda *_a, **_k: list(steps))


def ask(client: TestClient, question: str, patient: str | None, screen: str = "patient"):  # type: ignore[no-untyped-def]
    ask_limiter.reset()
    return client.post(
        "/copilot/ask",
        json={"question": question, "screen": screen, "patient_id": patient},
        headers=JSON,
    )


def test_a_denied_patient_stays_denied_when_the_router_says_lookup(
    users: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    force(monkeypatch, Step(route="lookup", confidence=0.99, reason="forced"))
    assistant = signed_in("assistant@demo.medynium")
    denied = ask(assistant, "what are the current medications?", S3)
    missing = ask(assistant, "what are the current medications?", "P-0000")
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json() == NOT_FOUND


def test_opening_a_denied_patient_by_name_is_the_same_as_a_name_that_matches_nobody(
    users: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    def step(name: str) -> Step:
        return Step(
            route="action",
            action="open_patient",
            params={"name_query": name},
            confidence=0.99,
            reason="forced",
        )

    assistant = signed_in("assistant@demo.medynium")
    force(monkeypatch, step("Amit Kumar"))
    denied = ask(assistant, "take me to that person", None, "dashboard")
    force(monkeypatch, step("Zzyzx Nobody"))
    missing = ask(assistant, "take me to that person", None, "dashboard")
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json() == NOT_FOUND


def test_an_action_outside_the_list_is_refused_even_when_the_router_proposes_it(
    users: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    force(
        monkeypatch,
        Step(
            route="action",
            action="update_medication",
            params={"patient_id": "P-1042"},
            confidence=0.99,
            reason="forced",
        ),
    )
    body = ask(signed_in("sharma@demo.medynium"), "do the thing", "P-1042").json()
    assert body["actions"] == [] and body["answer"] is None
    assert body["routes"][0]["route"] == "refuse" and body["refusal"]["reason"] in {
        "unlisted_action",
        "record_change",
    }
