"""One SNOWFLAKE.CORTEX.COMPLETE call under the service role. Used by the router (no patient data) and the
safety review (an evidence pack). Cost-effective models only; the model name is configuration, never code."""

import json
import time
from dataclasses import dataclass
from typing import Any

import structlog
from snowflake.connector.errors import Error as SnowflakeError

from medynium_api.core.errors import ApiError, ErrorCode
from medynium_api.core.snowflake.role_session import service_cursor

log = structlog.get_logger()

# "SQL execution canceled": the Cortex backend returns this intermittently (about one strong-model call in ten
# in the 2026-10-03 evaluation runs). One retry turns most of those into a slower success instead of an error.
TRANSIENT_ERRNOS = {604}


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    seconds: float
    prompt_tokens: int | None
    completion_tokens: int | None


def complete(
    model: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 700,
    temperature: float = 0.0,
    timeout: float | None = None,
) -> Completion:
    options = {"max_tokens": max_tokens, "temperature": temperature}
    started = time.perf_counter()
    raw: Any = None
    for attempt in range(2):
        try:
            with service_cursor() as cur:
                cur.execute(
                    "SELECT SNOWFLAKE.CORTEX.COMPLETE(%s, PARSE_JSON(%s), PARSE_JSON(%s)) AS R",
                    (model, json.dumps(messages), json.dumps(options)),
                    timeout=int(timeout) if timeout else None,
                )
                raw = cur.fetchone()["R"]
            break
        except SnowflakeError as exc:
            code = getattr(exc, "errno", None)
            if attempt == 0 and code in TRANSIENT_ERRNOS:
                log.warning("complete_retry", model=model, code=code)
                continue
            log.error("complete_failed", model=model, code=code)
            raise ApiError(
                ErrorCode.AGENT_UNAVAILABLE, "The language model is unavailable."
            ) from exc
    data = json.loads(raw) if isinstance(raw, str) else raw
    usage = data.get("usage", {}) if isinstance(data, dict) else {}
    try:
        text = data["choices"][0]["messages"] if isinstance(data, dict) else str(data)
    except (KeyError, IndexError, TypeError) as exc:
        raise ApiError(
            ErrorCode.AGENT_UNAVAILABLE, "The language model returned an unexpected reply."
        ) from exc
    return Completion(
        text=str(text), model=model, seconds=time.perf_counter() - started,
        prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
    )  # fmt: skip
