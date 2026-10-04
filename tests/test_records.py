"""The write contract and the service's error mapping, without Snowflake (live behaviour: tests/integration/test_records.py)."""

import datetime as dt
from typing import Any

import pytest
from pydantic import ValidationError

from medynium_api.core.config import Settings
from medynium_api.core.errors import ApiError
from medynium_api.core.session import Session
from medynium_api.features.records import service as service_module
from medynium_api.features.records.schemas import (
    ArchiveBody,
    DiagnosisIn,
    LabIn,
    MedicationIn,
    MedicationUpdate,
    NoteIn,
    PatientCreate,
    VisitIn,
)
from medynium_api.features.records.service import RecordService, changed_fields, payload_of

TODAY = dt.date.today()


def patient(**over: Any) -> dict[str, Any]:
    return {"full_name": "Asha Verma", "birth_date": "1980-05-05", "sex": "F", **over}


# Validation ---------------------------------------------------------------------------------------------------
def test_unknown_and_privileged_fields_are_refused() -> None:
    for extra in (
        {"is_archived": True},
        {"patient_id": "P-1"},
        {"version": 3},
        {"entered_by": "x"},
    ):
        with pytest.raises(ValidationError):
            DiagnosisIn(description="Hypertension", **extra)


@pytest.mark.parametrize(
    "bad",
    [
        patient(pin_code="12345"),
        patient(phone="abc"),
        patient(sex="X"),
        patient(full_name="  "),
        patient(birth_date=str(TODAY + dt.timedelta(days=30))),
        patient(birth_date="1800-01-01"),
    ],
)
def test_a_bad_patient_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PatientCreate(**bad)


def test_a_good_patient_is_accepted_and_trimmed() -> None:
    p = PatientCreate(
        **patient(full_name="  Asha Verma ", pin_code="411001", phone="+91 98765 43210")
    )
    assert p.full_name == "Asha Verma" and p.confirm_duplicate is False


def test_dates_must_run_forwards() -> None:
    with pytest.raises(ValidationError):
        DiagnosisIn(description="x", onset_date="2024-05-01", resolved_date="2024-01-01")
    with pytest.raises(ValidationError):
        MedicationIn(description="Metformin", start_date="2024-05-01", stop_date="2024-01-01")
    with pytest.raises(ValidationError):
        VisitIn(
            started_at="2024-05-02T10:00:00",
            ended_at="2024-05-02T09:00:00",
            visit_kind="OUTPATIENT",
        )


def test_the_future_is_refused() -> None:
    soon = (dt.datetime.now(dt.UTC) + dt.timedelta(days=3)).isoformat()
    with pytest.raises(ValidationError):
        LabIn(loinc_code="33914-3", value_num=50, observed_at=soon)
    with pytest.raises(ValidationError):
        NoteIn(title="t", body="b", note_date=str(TODAY + dt.timedelta(days=9)))


def test_a_naive_time_is_read_as_ist_and_stored_as_utc() -> None:
    lab = LabIn(loinc_code="33914-3", value_num=42.5, observed_at="2026-09-01T10:30:00")
    assert lab.observed_at == dt.datetime(2026, 9, 1, 5, 0, 0)  # 10:30 IST is 05:00 UTC
    zoned = LabIn(loinc_code="33914-3", value_num=1, observed_at="2026-09-01T10:30:00+00:00")
    assert zoned.observed_at == dt.datetime(2026, 9, 1, 10, 30, 0)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, 2_000_000.0])
def test_an_implausible_lab_value_is_refused(value: float) -> None:
    with pytest.raises(ValidationError):
        LabIn(loinc_code="33914-3", value_num=value, observed_at="2026-09-01T10:30:00")


def test_the_payload_never_carries_the_version_or_flags() -> None:
    body = MedicationUpdate(description="Glycomet 500", dose_text="500 mg", version=4)
    sent = payload_of(body)
    assert "version" not in sent and sent["description"] == "Glycomet 500"
    assert "confirm_duplicate" not in payload_of(PatientCreate(**patient(confirm_duplicate=True)))
    assert ArchiveBody(version=2).reason is None


# Service ------------------------------------------------------------------------------------------------------
class FakeRepo:
    def __init__(self, result: dict[str, Any] | None = None, duplicate: bool = False) -> None:
        self.result = result or {"ok": True, "patient_id": "P-1", "record_id": "RX-9", "version": 1}
        self.duplicate = duplicate
        self.sent: list[tuple[Any, ...]] = []

    def find_duplicate(self, *_a: Any) -> bool:
        return self.duplicate

    def register_patient(self, *args: Any) -> dict[str, Any]:
        self.sent.append(("register", *args))
        return {"ok": True, "patient_id": "P-2301", "record_id": "P-2301", "version": 1}

    def write(self, *args: Any) -> dict[str, Any]:
        self.sent.append(("write", *args))
        return self.result


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    log: list[Any] = []
    monkeypatch.setattr(service_module, "require_patient", lambda *_a: None)
    monkeypatch.setattr(service_module, "clear_cache", lambda *_a: None)
    monkeypatch.setattr(
        service_module, "write_audit", lambda _s, entry, **_k: log.append(entry) or "A"
    )
    monkeypatch.setattr(service_module, "pad", lambda *_a: None)
    monkeypatch.setattr(service_module.write_limiter, "check", lambda *_a: None)
    monkeypatch.setattr(service_module.refresh_worker, "submit", lambda *_a: None)
    monkeypatch.setattr(service_module.refresh_worker, "refresh_now", lambda *_a: True)
    return log


def session() -> Session:
    return Session(
        "a" * 8 + "-0000-0000-0000-" + "b" * 12, "DOCTOR", False, "s", 1, dt.datetime(2030, 1, 1)
    )


def service(repo: FakeRepo) -> RecordService:
    return RecordService(Settings(demo_as_of_date="2026-10-02"), repo)  # type: ignore[arg-type]


def test_a_write_is_sent_with_the_actor_audited_and_returns_the_new_version(
    audits: list[Any],
) -> None:
    repo = FakeRepo()
    out = service(repo).create(
        session(), "P-1", "medications", MedicationIn(description="Glycomet"), "k1"
    )
    assert (out.record_id, out.version) == ("RX-9", 1)
    _kind, actor, entity, op, pid, record, version, payload, key, _reason, as_of = repo.sent[0]
    assert (entity, op, pid, record, version, key, as_of) == (
        "MEDICATION",
        "CREATE",
        "P-1",
        None,
        None,
        "k1",
        "2026-10-02",
    )
    assert actor == session().user_id and payload["description"] == "Glycomet"
    assert [a.action for a in audits] == ["WRITE_MEDICATION_CREATE"] and audits[0].outcome == "OK"


@pytest.mark.parametrize("error", ["denied", "not_found"])
def test_denied_and_missing_are_the_same_404(audits: list[Any], error: str) -> None:
    repo = FakeRepo({"ok": False, "error": error})
    with pytest.raises(ApiError) as caught:
        service(repo).create(
            session(), "P-1", "allergies", MedicationIn(description="Penicillin"), None
        )
    assert (
        caught.value.status_code == 404
        and caught.value.message == "The requested resource was not found."
    )


@pytest.mark.parametrize(
    ("error", "status"), [("conflict", 409), ("invalid", 422), ("forbidden", 403)]
)
def test_each_database_error_maps_to_its_status(audits: list[Any], error: str, status: int) -> None:
    repo = FakeRepo({"ok": False, "error": error, "detail": "unknown test"})
    with pytest.raises(ApiError) as caught:
        service(repo).update(
            session(), "P-1", "labs", "LAB-1", MedicationIn(description="x" * 3), 3, None
        )
    assert caught.value.status_code == status
    assert audits[-1].outcome == "ERROR"


def test_an_entitlement_miss_is_audited_as_denied_before_anything_is_sent(
    audits: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny(*_a: Any) -> None:
        raise ApiError(__import__("medynium_api.core.errors", fromlist=["x"]).ErrorCode.NOT_FOUND)

    monkeypatch.setattr(service_module, "require_patient", deny)
    repo = FakeRepo()
    with pytest.raises(ApiError):
        service(repo).create(session(), "P-1", "notes", NoteIn(title="t", body="b"), None)
    assert repo.sent == [] and audits[0].outcome == "DENIED"


def test_registering_a_duplicate_needs_confirmation(audits: list[Any]) -> None:
    with pytest.raises(ApiError) as caught:
        service(FakeRepo(duplicate=True)).register_patient(
            session(), PatientCreate(**patient()), None
        )
    assert caught.value.status_code == 409
    repo = FakeRepo(duplicate=True)
    out = service(repo).register_patient(
        session(), PatientCreate(**patient(confirm_duplicate=True)), None
    )
    assert out.patient_id == "P-2301" and audits[-1].action == "WRITE_PATIENT_CREATE"


def test_the_changed_fields_come_from_the_two_images() -> None:
    before = '{"DOSE_TEXT": "500 mg", "DESCRIPTION": "Metformin", "VERSION": 1, "UPDATED_AT": "a"}'
    after = '{"DOSE_TEXT": "1000 mg", "DESCRIPTION": "Metformin", "VERSION": 2, "UPDATED_AT": "b"}'
    assert changed_fields(before, after) == ["dose_text"]
    assert changed_fields(None, after) == []
