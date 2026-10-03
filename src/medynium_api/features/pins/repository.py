"""Pins under the caller's role. ANSWER_EVIDENCE and PIN carry the own-rows-and-entitled policy, so an answer
that is not the caller's (or a patient they lost) simply is not found."""

from typing import Any

from medynium_api.core.snowflake.queries import Row, execute, fetch_all, fetch_one
from medynium_api.core.snowflake.role_session import user_cursor

PIN_COLUMNS = "PIN_ID, ANSWER_ID, EVIDENCE_ID, LABEL, NOTE, CREATED_AT"


class PinRepository:
    def list_pins(self, role: str, patient_id: str) -> list[Row]:
        with user_cursor(role) as cur:
            return fetch_all(
                cur,
                f"SELECT {PIN_COLUMNS} FROM ANALYTICS.PIN WHERE PATIENT_ID = %s ORDER BY CREATED_AT DESC",
                (patient_id,),
            )

    def create(
        self,
        role: str,
        user_id: str,
        patient_id: str,
        answer_id: str,
        evidence_id: str,
        note: str | None,
        pin_id: str,
        key: str | None,
    ) -> Row | None:
        """The pin, or None if the evidence is not visible to the caller for this patient."""
        with user_cursor(role) as cur:
            if key:
                existing = fetch_one(
                    cur,
                    f"SELECT {PIN_COLUMNS} FROM ANALYTICS.PIN WHERE USER_ID = %s AND IDEMPOTENCY_KEY = %s",
                    (user_id, key),
                )
                if existing:
                    return existing
            evidence = fetch_one(
                cur,
                "SELECT EVIDENCE_KIND, VALUE_TEXT, SOURCE_SNAPSHOT FROM ANALYTICS.ANSWER_EVIDENCE "
                "WHERE ANSWER_ID = %s AND EVIDENCE_ID = %s AND PATIENT_ID = %s",
                (answer_id, evidence_id, patient_id),
            )
            if not evidence:
                return None
            execute(
                cur,
                "INSERT INTO ANALYTICS.PIN (PIN_ID, USER_ID, PATIENT_ID, ANSWER_ID, EVIDENCE_ID, LABEL, NOTE, "
                "IDEMPOTENCY_KEY, CREATED_AT) SELECT %s, %s, %s, %s, %s, %s, %s, %s, SYSDATE()",
                (
                    pin_id,
                    user_id,
                    patient_id,
                    answer_id,
                    evidence_id,
                    label_for(evidence),
                    note,
                    key,
                ),
            )
            return fetch_one(
                cur, f"SELECT {PIN_COLUMNS} FROM ANALYTICS.PIN WHERE PIN_ID = %s", (pin_id,)
            )

    def delete(self, role: str, patient_id: str, pin_id: str) -> int:
        with user_cursor(role) as cur:
            return execute(
                cur,
                "DELETE FROM ANALYTICS.PIN WHERE PIN_ID = %s AND PATIENT_ID = %s",
                (pin_id, patient_id),
            )


def label_for(evidence: dict[str, Any]) -> str:
    from medynium_api.core.snowflake.queries import json_value

    snapshot = json_value(evidence.get("source_snapshot")) or {}
    if snapshot:
        parts = [snapshot.get("title"), snapshot.get("section"), snapshot.get("version")]
        return ": ".join(str(p) for p in parts[:2] if p) + (f", {parts[2]}" if parts[2] else "")
    return str(evidence.get("value_text") or "Pinned evidence")[:200]
