"""API-side entitlement check: the second layer behind the row access policy (SEC-02, SRS 3.1).

Entitled patient ids per user are cached for 30 seconds, so a revocation takes effect within 30 s and a
request costs no extra query. A denied patient and a missing one both end in the same `not_found`.
"""

import threading
import time

import structlog

from medynium_api.core.errors import not_found
from medynium_api.core.session import Session
from medynium_api.core.snowflake.queries import fetch_all
from medynium_api.core.snowflake.role_session import service_cursor

log = structlog.get_logger()
TTL_SECONDS = 30.0
_cache: dict[str, tuple[float, frozenset[str]]] = {}
_lock = threading.Lock()


def entitled_patients(user_id: str) -> frozenset[str]:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(user_id)
        if hit and hit[0] > now:
            return hit[1]
    with service_cursor() as cur:
        rows = fetch_all(
            cur,
            "SELECT PATIENT_ID FROM SECURITY.PATIENT_ENTITLEMENT WHERE USER_ID = %s AND REVOKED_AT IS NULL",
            (user_id,),
        )
    ids = frozenset(r["patient_id"] for r in rows)
    with _lock:
        _cache[user_id] = (now + TTL_SECONDS, ids)
    return ids


def clear_cache(user_id: str | None = None) -> None:
    with _lock:
        if user_id is None:
            _cache.clear()
        else:
            _cache.pop(user_id, None)


def require_patient(session: Session, patient_id: str) -> None:
    """Raise the standard not_found unless the caller is entitled to this patient."""
    if patient_id not in entitled_patients(session.user_id):
        raise not_found()


def log_policy_disagreement(session: Session, patient_id: str) -> None:
    """The API said entitled but the policy returned nothing: a policy bug worth an alert."""
    log.error("entitlement_policy_disagreement", user_id=session.user_id, patient_id=patient_id)
