"""The `similar_patients` tool: the same search the Similar tab runs (core/similar.py), shown as statements. Each neighbour
is one statement with its reasons, and each is evidence the clinician can open. Read-only; never a prediction."""

import datetime as dt
from typing import Any

from medynium_api.core.evidence.models import SqlEvidence
from medynium_api.core.similar import DISCLAIMER, find_similar
from medynium_api.core.snowflake.queries import explain_sql


def run_similar(
    role: str,
    patient_id: str,
    weight: float,
    add: Any,
    group: str,
    recorded: list[SqlEvidence],
    sentences: list[str],
    notes: list[str],
) -> bool:
    """Add the open patient's closest matches. False when the patient is not visible (denied looks like missing)."""
    statements: list[tuple[str, list[Any], int]] = []
    result = find_similar(role, patient_id, 5, "blend", weight, statements)
    if result is None:
        return False
    for sql, params, n in statements:
        recorded.append(
            SqlEvidence(
                sql_id=f"Q{len(recorded) + 1}", role=role, text=explain_sql(sql, params), row_count=n,
                ran_at=dt.datetime.now(dt.UTC).replace(tzinfo=None),
            )
        )  # fmt: skip
    for m in result.matches:
        p = m.profile
        text = f"{p.name}, {p.age} {p.sex}: {round(m.score * 100)}% match. " + "; ".join(m.why)
        add(
            group,
            p.patient_id,
            text,
            "Similar patient",
            p.patient_id,
            "ANALYTICS.PATIENT_EMBEDDING",
            None,
        )
    n = len(result.matches)
    if not result.ready:
        sentences.append(
            "This patient was changed a moment ago and is still being prepared; ask again shortly."
        )
    elif n:
        sentences.append(f"{n} of your own patients are the closest to this one.")
    else:
        sentences.append("None of your own patients is similar enough to show.")
    notes.append(DISCLAIMER)
    return True
