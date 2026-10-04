"""Rebuild a patient's read models in the background after a write (snowflake/35_refresh_patient.sql).

A refresh takes about six seconds because each of its statements costs a round of compilation, so a write returns
without waiting for it. The write procedure queues the refresh in INTAKE.REFRESH_QUEUE first, so nothing is lost if
the API restarts; this worker then refreshes the patient and marks the queue rows done, and a sweeper retries any
refresh that is overdue. Several writes to one patient before the worker gets to it share one refresh.

Needs CPU after the response is sent: the Cloud Run service is deployed with --no-cpu-throttling.
"""

import queue
import threading
import time

import structlog

from medynium_api.core.config import get_settings
from medynium_api.core.intel import doctors
from medynium_api.core.snowflake.queries import json_value
from medynium_api.core.snowflake.role_session import service_cursor

log = structlog.get_logger()
SWEEP_SECONDS = 60
OVERDUE_AFTER_SECONDS = 45


def pending(patient_id: str) -> bool:
    """Is a refresh for this patient still owed? The screens show "updating" until it clears."""
    with service_cursor() as cur:
        cur.execute("CALL INTAKE.PENDING_REFRESH(%s)", (patient_id,))
        owed = int(next(iter(cur.fetchone().values())) or 0) > 0
    # A refresh marks the queue rows it covers as done, including a write that landed while it was reading; that write
    # is rebuilt by the refresh queued behind it. Until that one has run, the screens must keep saying "updating".
    return owed or refresh_worker.busy(patient_id)


class RefreshWorker:
    def __init__(self, workers: int = 2) -> None:
        self._jobs: queue.Queue[tuple[str, int]] = queue.Queue()
        self._waiting: set[str] = set()
        self._locks: dict[str, threading.Lock] = {}
        self._queued: dict[str, int] = {}
        self._gen: dict[str, int] = {}  # writes queued so far, per patient
        self._covered: dict[str, int] = {}  # the newest of them a finished refresh has already read
        self._running: dict[str, int] = {}
        self._lock = threading.Lock()
        self._workers = workers
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    def submit(self, patient_id: str) -> None:
        """Ask for a refresh. A patient already waiting is not queued twice."""
        self.ensure_started()
        with self._lock:
            if patient_id in self._waiting:
                return
            self._queued[patient_id] = self._queued.get(patient_id, 0) + 1
            self._gen[patient_id] = generation = self._gen.get(patient_id, 0) + 1
            self._waiting.add(patient_id)
        self._jobs.put((patient_id, generation))

    def ensure_started(self) -> None:
        with self._lock:
            if self._threads and all(t.is_alive() for t in self._threads):
                return
            self._stop.clear()
            self._threads = [
                threading.Thread(target=self._work, name=f"refresh-{i}", daemon=True)
                for i in range(self._workers)
            ]
            self._threads.append(
                threading.Thread(target=self._sweep, name="refresh-sweeper", daemon=True)
            )
            for thread in self._threads:
                thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _work(self) -> None:
        while not self._stop.is_set():
            try:
                patient_id, generation = self._jobs.get(timeout=1)
            except queue.Empty:
                continue
            with self._lock:
                self._waiting.discard(
                    patient_id
                )  # a write that lands from now on queues a new refresh
                self._queued[patient_id] -= 1
                self._running[patient_id] = self._running.get(patient_id, 0) + 1
            try:
                self._locked_refresh(patient_id, generation)
            finally:
                self._done(patient_id)

    def _sweep(self) -> None:
        while not self._stop.wait(SWEEP_SECONDS):
            try:
                with service_cursor() as cur:
                    cur.execute("CALL INTAKE.OVERDUE_REFRESHES(%s)", (OVERDUE_AFTER_SECONDS,))
                    ids = json_value(next(iter(cur.fetchone().values()))) or []
                for patient_id in ids:
                    log.warning("refresh_overdue", patient_id=patient_id)
                    self.submit(str(patient_id))
            except Exception as exc:
                log.error("refresh_sweep_failed", error=type(exc).__name__)

    def busy(self, patient_id: str) -> bool:
        """Is a refresh for this patient queued or running in this process?"""
        with self._lock:
            return self._queued.get(patient_id, 0) + self._running.get(patient_id, 0) > 0

    def _done(self, patient_id: str) -> None:
        with self._lock:
            self._running[patient_id] -= 1

    def refresh_now(self, patient_id: str) -> bool:
        with self._lock:
            self._running[patient_id] = self._running.get(patient_id, 0) + 1
        try:
            return self._locked_refresh(patient_id)
        finally:
            self._done(patient_id)

    def _locked_refresh(self, patient_id: str, generation: int | None = None) -> bool:
        started = time.perf_counter()
        # One refresh per patient at a time: two overlapping rebuilds of the same patient (a second write while the
        # first refresh runs) interleave their delete and insert and leave duplicate rows in the read models.
        with self._patient_lock(patient_id):
            with self._lock:
                if generation is not None and generation <= self._covered.get(patient_id, 0):
                    return True  # a refresh that started after this write has already read it
                read_up_to = self._gen.get(patient_id, 0)  # every write queued so far is committed
            done = self._refresh(patient_id, started)
            doctors.forget(patient_id)  # whatever changed, the doctor behind it may have too
            if done:
                with self._lock:
                    self._covered[patient_id] = max(self._covered.get(patient_id, 0), read_up_to)
            return done

    def _patient_lock(self, patient_id: str) -> threading.Lock:
        with self._lock:
            return self._locks.setdefault(patient_id, threading.Lock())

    @staticmethod
    def _refresh(patient_id: str, started: float) -> bool:
        try:
            with service_cursor() as cur:
                cur.execute(
                    "CALL INTAKE.REFRESH_QUEUED(%s, %s::DATE)",
                    (patient_id, get_settings().as_of_iso),
                )
                cur.fetchall()
        except Exception as exc:
            log.error("refresh_failed", patient_id=patient_id, error=type(exc).__name__)
            return False
        log.info(
            "refresh_done", patient_id=patient_id, ms=round((time.perf_counter() - started) * 1000)
        )
        return True


refresh_worker = RefreshWorker()
