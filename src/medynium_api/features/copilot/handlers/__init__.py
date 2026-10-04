"""Route handlers. Each takes a Ctx, emits steps and one result event (answer or refusal), and never skips the
server checks: the caller has already been entitled to the patient, and every query runs under the caller's role."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from medynium_api.core.config import Settings
from medynium_api.core.cortex.search_client import SearchClient
from medynium_api.core.evidence.models import RouteInfo
from medynium_api.core.session import Session
from medynium_api.features.copilot.repository import CopilotQueries, CopilotRepository
from medynium_api.features.copilot.routing import Step

if TYPE_CHECKING:
    from medynium_api.features.copilot.ports import Ports
    from medynium_api.features.copilot.safety import SafetyReview


@dataclass
class Ctx:
    settings: Settings
    session: Session
    patient_id: str | None
    question: str
    step: Step
    info: RouteInfo
    repo: CopilotRepository
    queries: CopilotQueries
    search: SearchClient
    history: list[str] = field(default_factory=list)
    safety: "SafetyReview | None" = None
    ports: "Ports | None" = None
    last_answer_id: str | None = None
