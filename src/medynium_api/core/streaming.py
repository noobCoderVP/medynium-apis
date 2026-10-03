"""Server-sent events for runs that take seconds (docs/api/README.md). Not resumable.

`Run` is what the work function receives: it records events and steps. A step is emitted by the code that actually
performs it, with its real duration, so the steps shown to the user equal the steps written to the audit row
(FR-21, AI-12). Nothing here fabricates progress.
"""

import json
import queue
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import anyio
import structlog
from fastapi import Request
from sse_starlette.sse import EventSourceResponse

from medynium_api.core.errors import ApiError, ErrorCode

log = structlog.get_logger()
_DONE = object()


@dataclass
class StepHandle:
    detail: str | None = None


class Run:
    def __init__(self, sink: "queue.Queue[Any] | None" = None) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.steps: list[dict[str, Any]] = []
        self.audit_id: str | None = None
        self._sink = sink

    def emit(self, event: str, data: dict[str, Any]) -> None:
        self.events.append((event, data))
        if self._sink is not None:
            self._sink.put((event, data))

    @contextmanager
    def step(self, label: str) -> Iterator[StepHandle]:
        step_id = f"s{len(self.steps) + 1}"
        record: dict[str, Any] = {"step_id": step_id, "label": label, "status": "running"}
        self.steps.append(record)
        self.emit("step", dict(record))
        handle = StepHandle()
        started = time.perf_counter()
        try:
            yield handle
        except BaseException:
            record.update(status="failed", ms=round((time.perf_counter() - started) * 1000))
            self.emit("step", dict(record))
            raise
        record.update(status="done", ms=round((time.perf_counter() - started) * 1000))
        if handle.detail:
            record["detail"] = handle.detail
        self.emit("step", dict(record))

    def last(self, event: str) -> dict[str, Any] | None:
        return next((d for e, d in reversed(self.events) if e == event), None)


def error_payload(exc: Exception) -> dict[str, str]:
    if isinstance(exc, ApiError):
        return {"error": exc.code.value, "message": exc.message}
    log.error("stream_failed", exc_type=type(exc).__name__, exc_info=exc)
    return {"error": ErrorCode.INTERNAL.value, "message": "Something went wrong."}


def stream_response(request: Request, work: Callable[[Run], None]) -> EventSourceResponse:
    """Run `work` in a thread and stream what it emits. A failure becomes an `error` event, then `done`."""
    sink: queue.Queue[Any] = queue.Queue()

    def target() -> None:
        run = Run(sink)
        try:
            work(run)
        except Exception as exc:
            sink.put(("error", error_payload(exc)))
        finally:
            sink.put(("done", {"audit_id": run.audit_id}))
            sink.put(_DONE)

    threading.Thread(target=target, daemon=True).start()

    async def events() -> AsyncIterator[dict[str, str]]:
        while True:
            item = await anyio.to_thread.run_sync(sink.get)
            if item is _DONE:
                return
            name, data = item
            yield {"event": name, "data": json.dumps(data, default=str)}

    return EventSourceResponse(events(), ping=15)


def collect(work: Callable[[Run], None]) -> Run:
    """JSON mode: run to completion and return the recorded events. Errors propagate as ApiError."""
    run = Run()
    work(run)
    return run
