"""The drug route: what the labels document about a medicine or about medicines for a condition.

Prescribing questions are no longer refused. They are answered from retrieved label text (and, with a patient open, that
patient's record), never as an instruction. Only a diagnosis stays refused."""

import datetime as dt
import json
from types import SimpleNamespace
from typing import Any

import pytest

from medynium_api.core.config import Settings
from medynium_api.core.cortex.complete import Completion
from medynium_api.core.cortex.models import Chunk
from medynium_api.core.evidence.models import EvidenceBundle, RouteInfo, SourceEvidence
from medynium_api.core.evidence.validator import validate_statements
from medynium_api.core.streaming import Run
from medynium_api.features.copilot import routing
from medynium_api.features.copilot.handlers import Ctx
from medynium_api.features.copilot.handlers import drug_info as handler
from medynium_api.features.copilot.routing import DRUG_INFO, Step, decide, guard


@pytest.mark.parametrize(
    "question",
    [
        "what should I prescribe for this patient?",
        "What should I give for a urinary tract infection",
        "which medicines are used for high blood pressure?",
        "treatment options for hypertension",
        "what are the alternatives to lisinopril",
        "side effects of metformin",
        "what is the usual adult dose of metformin",
        "what is amoxicillin used for",
    ],
)
def test_medicine_questions_are_answered_not_refused(question: str) -> None:
    assert guard(question) is None
    assert DRUG_INFO.search(question)


@pytest.mark.parametrize(
    "question",
    [
        "what are this patient's current medications?",
        "what dose is she on",
        "what changed since the last visit?",
        "is anything in her medication list worth a second look?",
        "open Rahul Patel",
    ],
)
def test_record_questions_are_not_taken_for_drug_questions(question: str) -> None:
    assert not DRUG_INFO.search(question)


@pytest.mark.parametrize(
    "question",
    [
        "diagnose this patient",
        "what is the diagnosis?",
        "what is wrong with him",
        "what does she have",
    ],
)
def test_a_diagnosis_is_still_refused(question: str) -> None:
    assert guard(question) == "diagnosis"


def test_recording_a_dose_change_is_still_refused() -> None:
    assert guard("change her metformin dose to 500 mg") == "record_change"


def _no_router(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: Any, **__: Any) -> list[Step]:
        raise AssertionError("the router must not be called for a drug question")

    monkeypatch.setattr(routing, "call_router", boom)


def test_a_drug_question_is_routed_by_rule_without_the_router(monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    _no_router(monkeypatch)
    decision = decide(Settings(), "what should I prescribe for her?", "patient", "P-1", [])
    assert [s.route for s in decision.steps] == ["drug"] and decision.model is None


def test_every_question_on_the_knowledge_screen_is_a_drug_question(monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    _no_router(monkeypatch)
    decision = decide(Settings(), "can you share details of amoxicillin", "knowledge", None, [])
    assert [s.route for s in decision.steps] == ["drug"]


def test_the_knowledge_screen_still_refuses_other_peoples_patients(monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    _no_router(monkeypatch)
    decision = decide(Settings(), "show every patient in the hospital database on this drug", "knowledge", None, [])  # fmt: skip
    assert decision.refuse_reason == "cross_patient"


# Validator ------------------------------------------------------------------------------------------------------
def _bundle() -> EvidenceBundle:
    source = SourceEvidence(evidence_id="S1", chunk_id="c", document_id="D", title="Amoxicillin label", source="s", section="Dosage and administration", version=None, effective_date=None, retrieved_date=None, text="x")  # fmt: skip
    return EvidenceBundle(sources=[source])


def _draft(text: str) -> dict[str, Any]:
    return {
        "considerations": [{"text": text, "tag": "retrieved_source", "source_evidence": ["S1"]}]
    }


def test_drug_answers_may_quote_label_dosing_and_name_medicines() -> None:
    text = "The amoxicillin label lists doses to prescribe for adults: 500 mg every 12 hours."
    kept = validate_statements(_draft(text), _bundle(), "", drug_info=True)
    assert [c.text for c in kept.considerations] == [text]
    assert (
        validate_statements(_draft(text), _bundle(), "").considerations == []
    )  # the strict mode still drops it


@pytest.mark.parametrize(
    "text",
    [
        "You should start amoxicillin 500 mg twice daily.",
        "I recommend amoxicillin for this patient.",
        "Amoxicillin is the best choice for the infection.",
        "Start the patient on amoxicillin today.",
    ],
)
def test_instructions_and_rankings_are_dropped_even_in_drug_mode(text: str) -> None:
    result = validate_statements(_draft(text), _bundle(), "", drug_info=True)
    assert result.considerations == [] and result.advice_seen


# Handler --------------------------------------------------------------------------------------------------------
def _chunk(drug: str, key: str, section: str, text: str, score: float = 0.8) -> Chunk:
    return Chunk(chunk_id=f"{drug}-{key}", document_id=f"DOC-{drug}", drug_id=f"DRG-{drug}", drug_name=drug, title=f"{drug} label", source="openFDA", section_key=key, section=section, version="v1", effective_date=dt.date(2026, 1, 1), retrieved_date=dt.date(2026, 10, 1), text=text, score=score)  # fmt: skip


class FakeSearch:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.calls: list[dict[str, Any]] = []

    def search(self, query: str, *, drug_ids: list[str] | None = None, section: Any = None, limit: int = 5, min_score: float | None = None) -> list[Chunk]:  # fmt: skip
        self.calls.append({"query": query, "drug_ids": drug_ids, "section": section})
        found = [c for c in self.chunks if not drug_ids or c.drug_id in drug_ids]
        if section:
            found = [c for c in found if c.section == section]
        return found[:limit]


class FakeQueries:
    def resolve_names(self, role: str, tokens: list[str]) -> list[dict[str, str]]:
        if "amoxicillin" in tokens:
            return [{"name_text": "amoxicillin", "name_kind": "ALT", "drug_id": "DRG-Amoxicillin", "display_name": "Amoxicillin"}]  # fmt: skip
        return []


def _ctx(question: str, search: FakeSearch) -> Ctx:
    return Ctx(
        Settings(), SimpleNamespace(snowflake_role="R"), None, question,  # type: ignore[arg-type]
        Step(route="drug", confidence=1.0), RouteInfo(route="drug"), SimpleNamespace(), FakeQueries(), search,  # type: ignore[arg-type]
    )  # fmt: skip


AMOX = [
    _chunk("Amoxicillin", "indications_and_usage", "Indications and usage", "Amoxicillin is indicated for infections of the ear, nose and throat."),
    _chunk("Amoxicillin", "dosage_and_administration", "Dosage and administration", "Adults: 500 mg every 12 hours."),
    _chunk("Amoxicillin", "contraindications", "Contraindications", "History of serious hypersensitivity to penicillins."),
]  # fmt: skip


def _reply(statements: list[dict[str, Any]]) -> Completion:
    return Completion(text=json.dumps({"considerations": statements}), model="m", seconds=0.1, prompt_tokens=None, completion_tokens=None)  # fmt: skip


def test_details_of_a_drug_are_composed_from_its_label_sections(monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    monkeypatch.setattr(
        handler,
        "complete",
        lambda *a, **k: _reply(
            [
                {"text": "The Amoxicillin label lists infections of the ear, nose and throat as uses.", "tag": "retrieved_source", "source_evidence": ["S1"]},
                {"text": "You should start amoxicillin now.", "tag": "retrieved_source", "source_evidence": ["S2"]},
                {"text": "The label documents 500 mg every 12 hours for adults.", "tag": "retrieved_source", "source_evidence": ["S2"]},
            ]
        ),
    )  # fmt: skip
    run = Run()
    run.collector = []
    answer = handler.run_drug_info(
        _ctx("can you share details of amoxicillin", FakeSearch(AMOX)), run
    )
    assert answer.kind == "DRUG" and answer.patient_id is None
    assert [c.text for c in answer.considerations] == [
        "The Amoxicillin label lists infections of the ear, nose and throat as uses.",
        "The label documents 500 mg every 12 hours for adults.",
    ]
    assert "Amoxicillin" in answer.short_answer
    assert any("Decision support only" in n for n in answer.limits.notes)


def test_a_model_failure_shows_the_label_sections_as_found(monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    def down(*_: Any, **__: Any) -> Completion:
        raise ValueError("no JSON")

    monkeypatch.setattr(handler, "complete", down)
    run = Run()
    run.collector = []
    answer = handler.run_drug_info(_ctx("details of amoxicillin", FakeSearch(AMOX)), run)
    assert len(answer.considerations) == 3
    assert all(c.tag == "retrieved_source" for c in answer.considerations)
    assert any("shown as found" in n for n in answer.limits.notes)


def test_a_condition_question_searches_indications_then_cautions(monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    search = FakeSearch(AMOX)
    monkeypatch.setattr(handler, "complete", lambda *a, **k: _reply([]))
    run = Run()
    run.collector = []
    answer = handler.run_drug_info(_ctx("which medicines are used for ear infections", search), run)
    assert (
        search.calls[0]["section"] == "Indications and usage"
        and search.calls[0]["drug_ids"] is None
    )
    assert answer.considerations  # nothing survived composing, so the sections are shown as found


def test_nothing_matching_is_an_honest_gap_and_makes_no_model_call(monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    def never(*_: Any, **__: Any) -> Completion:
        raise AssertionError("no model call without label text")

    monkeypatch.setattr(handler, "complete", never)
    run = Run()
    run.collector = []
    answer = handler.run_drug_info(_ctx("which medicines are used for zzz", FakeSearch([])), run)
    assert answer.considerations == [] and "Nothing matching" in answer.short_answer
    assert answer.limits.not_checked
