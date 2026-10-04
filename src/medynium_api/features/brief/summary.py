"""The short written summary of the brief. The facts come from the rules (attention, changes, gaps); a model may only
rephrase them, and anything it adds is thrown away: every number must already be in the signals, no advice, no
reassurance. If the model is unavailable or fails the check, the rule-made headline is used instead."""

import hashlib
import re
import threading
import time

import structlog

from medynium_api.core.config import Settings
from medynium_api.core.cortex.complete import complete
from medynium_api.core.errors import ApiError
from medynium_api.core.evidence.validator import ADVICE, FALSE_REASSURANCE, INSTRUCTION_LIKE
from medynium_api.features.brief.schemas import SummaryResponse

log = structlog.get_logger()
TTL_SECONDS = 20 * 60
MAX_CACHED = 256
NUMBER = re.compile(r"\d+(?:\.\d+)?")
PROMPT = (
    "You summarise a patient for the clinician who is about to open the chart. Use ONLY the SIGNALS below. "
    'Write two or three plain sentences, at most 70 words. Refer to the person as "the patient". Put the most '
    "important signals first. Do not add any number, date, test, medicine or diagnosis that is not in the SIGNALS. "
    "Do not diagnose, recommend, start, stop or dose anything, and never say something is safe or carries no risk. "
    "If there is nothing needing attention, say so plainly. Reply with the sentences only."
)
_cache: dict[str, tuple[float, SummaryResponse]] = {}
_lock = threading.Lock()


def acceptable(text: str, signals: str) -> bool:
    if not 30 <= len(text) <= 520:
        return False
    if ADVICE.search(text) or FALSE_REASSURANCE.search(text) or INSTRUCTION_LIKE.search(text):
        return False
    allowed = set(NUMBER.findall(signals))
    return all(n in allowed for n in NUMBER.findall(text))


def summarise(settings: Settings, patient_id: str, signals: str, fallback: str) -> SummaryResponse:
    key = patient_id + hashlib.sha256(signals.encode()).hexdigest()[:16]
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    result = SummaryResponse(patient_id=patient_id, summary=fallback, source="rules")
    try:
        reply = complete(
            settings.strong_model,
            [
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": f"SIGNALS\n{signals}"},
            ],
            max_tokens=220,
            timeout=settings.agent_timeout_seconds,
        )
        text = " ".join(reply.text.split())
        if acceptable(text, signals):
            result = SummaryResponse(
                patient_id=patient_id, summary=text, source="model", model=reply.model
            )
        else:
            log.warning("brief_summary_rejected", length=len(text))
    except ApiError:
        log.warning("brief_summary_unavailable")
    with _lock:
        if len(_cache) >= MAX_CACHED:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (now + TTL_SECONDS, result)
    return result
