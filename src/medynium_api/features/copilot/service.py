"""Copilot orchestration: route -> handler -> validate -> store -> audit (A-9 to A-12).

Every request follows the same order: rate limit, entitlement to the open patient (denied equals missing, audited),
rule guards and the router, then the handler for each step. A step never skips the server checks."""

import time
from typing import Any

import structlog

from medynium_api.core.access import require_patient
from medynium_api.core.audit.writer import AuditEntry, write_audit
from medynium_api.core.config import Settings
from medynium_api.core.cortex.search_client import SearchClient
from medynium_api.core.errors import ApiError, ErrorCode, not_found
from medynium_api.core.evidence.models import RouteInfo
from medynium_api.core.security.ratelimit import ask_limiter
from medynium_api.core.session import Session
from medynium_api.core.snowflake.timing import pad
from medynium_api.core.streaming import Run
from medynium_api.features.copilot.actions import Executor
from medynium_api.features.copilot.handlers import Ctx
from medynium_api.features.copilot.handlers.analyst import run_analyst
from medynium_api.features.copilot.handlers.knowledge import run_knowledge
from medynium_api.features.copilot.handlers.lookup import CHANGED, classify, run_changed, run_lookup
from medynium_api.features.copilot.handlers.refuse import run_refuse
from medynium_api.features.copilot.ports import Ports
from medynium_api.features.copilot.repository import CopilotQueries, CopilotRepository
from medynium_api.features.copilot.routing import NEEDS_PATIENT, Decision, Step, decide
from medynium_api.features.copilot.safety import SafetyReview

log = structlog.get_logger()


class CopilotService:
    def __init__(
        self,
        settings: Settings,
        ports: Ports,
        repo: CopilotRepository | None = None,
        search: SearchClient | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo or CopilotRepository()
        self.queries = CopilotQueries()
        self.search = search or SearchClient(settings)
        self.safety = SafetyReview(settings, self.repo, self.search)
        self.executor = Executor(ports, self.safety)

    def precheck(self, session: Session, patient_id: str, question: str | None) -> None:
        """Entitlement before a stream opens: a denied or missing patient is a plain 404, audited, same latency."""
        started = time.monotonic()
        try:
            require_patient(session, patient_id)
        except ApiError:
            write_audit(
                session,
                AuditEntry(
                    action="DENIED_PATIENT",
                    patient_id=patient_id,
                    question=question,
                    outcome="DENIED",
                ),
            )
            pad(started)
            raise not_found() from None

    # POST /patients/{id}/safety-review: the manual button, no router --------------------------------------------
    def safety_review(self, session: Session, patient_id: str, run: Run) -> None:
        ask_limiter.check(session.user_id)
        self.safety.run(session, patient_id, run)

    # POST /agent/actions ---------------------------------------------------------------------------------------
    def action(
        self, session: Session, action: str, params: dict[str, Any], run: Run
    ) -> dict[str, Any]:
        return self.executor.execute(session, action, params, run, via="USER")

    # POST /copilot/ask ------------------------------------------------------------------------------------------
    def ask(
        self,
        session: Session,
        question: str,
        screen: str,
        patient_id: str | None,
        history: list[str],
        run: Run,
    ) -> None:
        ask_limiter.check(session.user_id)
        log.info("ask_start", screen=screen, has_patient=bool(patient_id), history=len(history))
        if patient_id:
            self.precheck(session, patient_id, question)
            log.info("ask_entitled")
        decision = decide(self.settings, question, screen, patient_id, history)
        log.info(
            "ask_routed",
            routes=[s.route for s in decision.steps],
            model=decision.model,
            fallback=decision.fallback,
            escalated=decision.escalated,
        )
        context_patient = patient_id
        for index, step in enumerate(decision.steps, start=1):
            info = self._info(decision, step)
            log.info(
                "ask_step", n=index, of=len(decision.steps), route=step.route, reason=step.reason
            )
            step_started = time.monotonic()
            run.emit(
                "route",
                info.model_dump(mode="json")
                | {
                    "reason": step.reason,
                    "fallback": decision.fallback,
                    "escalated": decision.escalated,
                },
            )
            ctx = Ctx(
                self.settings,
                session,
                context_patient,
                question,
                step,
                info,
                self.repo,
                self.queries,
                self.search,
                history,
            )
            try:
                context_patient = (
                    self._dispatch(ctx, run, decision, context_patient) or context_patient
                )
            except ApiError as exc:
                log.warning("ask_step_failed", n=index, route=step.route, code=exc.code.value)
                run.audit_id = write_audit(
                    session,
                    AuditEntry(
                        action="ASK",
                        route=step.route,
                        model=info.model,
                        confidence=info.confidence,
                        patient_id=context_patient,
                        question=question,
                        steps=run.steps,
                        outcome="ERROR",
                        outcome_detail=exc.code.value,
                    ),
                )
                raise
            log.info(
                "ask_step_done", n=index, route=step.route,
                ms=round((time.monotonic() - step_started) * 1000),
            )  # fmt: skip

    def _info(self, decision: Decision, step: Step) -> RouteInfo:
        free = step.route in ("lookup", "action", "refuse", "knowledge")
        if decision.model is None:
            note = "rule guard, no model call"
        elif free:
            note = "router only, no generating model"
        else:
            note = "strong model" if step.route == "safety" else "Cortex Analyst"
        model = self.settings.strong_model if step.route == "safety" else decision.model
        return RouteInfo(
            route=step.route,
            model=model,
            confidence=step.confidence if decision.model else None,
            cost_note=note,
        )

    def _dispatch(
        self, ctx: Ctx, run: Run, decision: Decision, patient_id: str | None
    ) -> str | None:
        """Run one step; returns the patient id to carry to the next step when the step opened one."""
        route = ctx.step.route
        if route == "refuse":
            run_refuse(ctx, run, decision.refuse_reason or "unlisted_action")
            return None
        if route in NEEDS_PATIENT and not patient_id:
            run_refuse(ctx, run, "needs_patient")
            return None
        if route == "action":
            result = self.executor.execute(
                ctx.session,
                ctx.step.action or "",
                ctx.step.params,
                run,
                context_patient=patient_id,
                question=ctx.question,
            )
            return result.get("patient_id")
        try:
            if route == "lookup":
                kind = classify(ctx.question)
                if kind == "CHANGED":
                    run_changed(ctx, run)
                elif kind:
                    run_lookup(ctx, run, kind)
                else:
                    run_analyst(ctx, run)
            elif route == "analyst":
                run_changed(ctx, run) if CHANGED.search(ctx.question) else run_analyst(ctx, run)
            elif route == "knowledge":
                run_knowledge(ctx, run)
            else:
                self.safety.run(
                    ctx.session, patient_id or "", run, question=ctx.question, route=ctx.info
                )
        except LookupError:
            pad(time.monotonic())
            raise ApiError(ErrorCode.NOT_FOUND) from None
        return None
