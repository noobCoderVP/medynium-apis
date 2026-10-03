"""Cortex Analyst: question in, SQL out. Analyst never executes anything; the API runs the returned SQL under the
caller's own role, so the row access policy decides what comes back (spike S-A, step 4)."""

import re
from dataclasses import dataclass

import httpx
import structlog

from medynium_api.core.config import Settings
from medynium_api.core.cortex.auth import rest_headers
from medynium_api.core.errors import ApiError, ErrorCode

log = structlog.get_logger()
READ_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|grant|revoke|call|truncate|copy|put|get)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AnalystResult:
    sql: str | None
    explanation: str | None


def ask_analyst(settings: Settings, question: str, patient_id: str, role: str) -> AnalystResult:
    """Ask in the context of one patient, under the caller's own role (U_<id>, validated by the caller)."""
    scoped = f"For patient {patient_id} only (filter on patient id = '{patient_id}'): {question}"
    body = {
        "messages": [{"role": "user", "content": [{"type": "text", "text": scoped}]}],
        "semantic_view": settings.cortex_semantic_view,
    }
    try:
        response = httpx.post(
            f"https://{settings.snowflake_host}/api/v2/cortex/analyst/message",
            headers=rest_headers(settings, role),
            json=body,
            timeout=httpx.Timeout(settings.agent_timeout_seconds, connect=10.0),
        )
    except httpx.TimeoutException as exc:
        raise ApiError(ErrorCode.TIMEOUT, "The analysis timed out.") from exc
    except httpx.HTTPError as exc:
        raise ApiError(ErrorCode.AGENT_UNAVAILABLE, "The analysis service is unavailable.") from exc
    if response.status_code != 200:
        log.error("analyst_failed", status=response.status_code)
        raise ApiError(ErrorCode.AGENT_UNAVAILABLE, "The analysis service is unavailable.")
    content = response.json().get("message", {}).get("content", [])
    sql = next((c.get("statement") for c in content if c.get("type") == "sql"), None)
    text = next((c.get("text") for c in content if c.get("type") == "text"), None)
    return AnalystResult(sql=sql, explanation=text)


def safe_for_patient(sql: str, patient_id: str) -> bool:
    """Server-side guard on generated SQL: one read-only statement that names the patient in scope."""
    body = sql.strip().rstrip(";")
    return (
        bool(READ_ONLY.match(body))
        and ";" not in body
        and not FORBIDDEN.search(re.sub(r"'[^']*'", "''", body))
        and f"'{patient_id}'" in body
    )
