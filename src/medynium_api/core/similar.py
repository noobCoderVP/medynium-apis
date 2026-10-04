"""Similar-patient search (production plan Phase 5). Shared by the Similar tab (features/similar) and the assistant's
`similar_patients` tool (features/copilot), so a person and the assistant see the same neighbours.

How a match is scored. Two signals are blended, so the ranking both finds near-misses and can say why:
  * embedding similarity: the cosine between two case vectors. It catches "CKD stage 3" matching "chronic kidney
    disease" where the wording differs. Typical values run from about 0.3 (unrelated) to 0.9 (near-identical).
  * structured overlap, which explains the match: shared diagnoses, shared medicines, abnormal results in the same
    direction, and age.
Everything runs under the caller's own role. The embedding table carries the entitled-patient policy, so the candidates
can only ever be patients the caller already has. Nothing here predicts an outcome or recommends anything."""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from medynium_api.core.snowflake.queries import Row, fetch_all, json_value
from medynium_api.core.snowflake.role_session import user_cursor

Mode = Literal["blend", "structured", "embedding"]
WEIGHT_EMBEDDING = (
    0.5  # of the blend; the rest is structured overlap. Chosen with scripts/eval_similar.py.
)
STRUCTURED = {"diagnoses": 0.45, "medicines": 0.30, "labs": 0.15, "age": 0.10}
COSINE_LOW, COSINE_HIGH = 0.30, 0.90
CANDIDATES = 40
MIN_SCORE = (
    0.30  # below this a patient is not shown, so the list is never padded to look fuller than it is
)
DISCLAIMER = "For comparison only. Not a prediction and not a recommendation."


@dataclass(frozen=True)
class Profile:
    patient_id: str
    name: str
    age: int | None
    sex: str | None
    diagnoses: dict[str, str] = field(default_factory=dict)  # normalised name -> name as recorded
    medicines: dict[str, str] = field(default_factory=dict)
    labs: dict[str, tuple[float, str | None, str | None]] = field(
        default_factory=dict
    )  # test -> value, unit, flag


@dataclass(frozen=True)
class Match:
    profile: Profile
    score: float
    parts: dict[str, float]
    shared_diagnoses: list[str]
    shared_medicines: list[str]
    lab_comparison: list[dict[str, Any]]
    why: list[str]


@dataclass
class Result:
    ready: bool
    matches: list[Match]
    candidates: int = 0


# Pure scoring ---------------------------------------------------------------------------------------------------
def normalise(text: str) -> str:
    """A diagnosis or drug name reduced to what makes it the same condition: case, brackets and stage are dropped, so
    "Chronic kidney disease, stage 3b" and "Chronic kidney disease stage 2" count as the same family."""
    value = re.sub(r"\([^)]*\)", "", text.lower())
    value = re.sub(r",?\s*stage\s*\w+", "", value)
    return re.sub(r"[^a-z0-9 ]+", " ", value).strip()


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def embedding_part(cosine: float) -> float:
    return min(1.0, max(0.0, (cosine - COSINE_LOW) / (COSINE_HIGH - COSINE_LOW)))


def abnormal(profile: Profile) -> set[str]:
    return {
        f"{test}:{flag}" for test, (_v, _u, flag) in profile.labs.items() if flag in ("LOW", "HIGH")
    }


def lab_agreement(a: Profile, b: Profile) -> float:
    x, y = abnormal(a), abnormal(b)
    return (
        jaccard(x, y) if x or y else 0.5
    )  # neither has an abnormal result: neither evidence for nor against


def age_closeness(a: Profile, b: Profile) -> float:
    if a.age is None or b.age is None:
        return 0.5
    return max(0.0, 1.0 - abs(a.age - b.age) / 30.0)


def blend(parts: dict[str, float], cosine_part: float, mode: Mode, weight: float) -> float:
    structured = sum(STRUCTURED[k] * parts[k] for k in STRUCTURED)
    if mode == "structured":
        return structured
    if mode == "embedding":
        return cosine_part
    return weight * cosine_part + (1 - weight) * structured


def compare(
    query: Profile,
    other: Profile,
    cosine: float,
    mode: Mode = "blend",
    weight: float = WEIGHT_EMBEDDING,
) -> Match:
    dx_keys = set(query.diagnoses) & set(other.diagnoses)
    rx_keys = set(query.medicines) & set(other.medicines)
    parts = {
        "embedding": round(embedding_part(cosine), 3),
        "diagnoses": round(jaccard(set(query.diagnoses), set(other.diagnoses)), 3),
        "medicines": round(jaccard(set(query.medicines), set(other.medicines)), 3),
        "labs": round(lab_agreement(query, other), 3),
        "age": round(age_closeness(query, other), 3),
    }
    shared_dx = sorted(query.diagnoses[k] for k in dx_keys)
    shared_rx = sorted(query.medicines[k] for k in rx_keys)
    comparison = [
        {"test": test, "this_value": mine[0], "other_value": theirs[0], "unit": mine[1] or theirs[1],
         "this_flag": mine[2], "other_flag": theirs[2]}
        for test, mine in sorted(query.labs.items())
        if (theirs := other.labs.get(test)) and ((mine[2] in ("LOW", "HIGH")) or (theirs[2] in ("LOW", "HIGH")))
    ]  # fmt: skip
    why = []
    if shared_dx:
        why.append("Both have " + ", ".join(shared_dx[:3]))
    if shared_rx:
        why.append("both on " + ", ".join(shared_rx[:3]))
    for c in comparison[:2]:
        why.append(
            f"{c['test']} {c['this_value']:g} vs {c['other_value']:g} {c['unit'] or ''}".strip()
        )
    if not why:
        why.append("Similar overall case picture, but no shared diagnosis or medicine")
    return Match(
        profile=other, score=round(blend(parts, parts["embedding"], mode, weight), 3), parts=parts,
        shared_diagnoses=shared_dx, shared_medicines=shared_rx, lab_comparison=comparison,
        why=[why[0][0].upper() + why[0][1:], *why[1:]],
    )  # fmt: skip


# Queries (the caller's role) ------------------------------------------------------------------------------------
def _marks(ids: list[str]) -> str:
    return ", ".join(["%s"] * len(ids))


def profiles(
    cur: Any, ids: list[str], statements: list[tuple[str, list[Any], int]]
) -> dict[str, Profile]:
    """Structured features for these patients from the read models. Each statement is noted for the Why? panel."""
    out: dict[str, dict[str, Any]] = {}

    def run(sql: str, params: list[Any]) -> list[Row]:
        rows = fetch_all(cur, sql, params)
        statements.append((sql, params, len(rows)))
        return rows

    for r in run(
        f"SELECT PATIENT_ID, FULL_NAME, AGE_YEARS, SEX, ACTIVE_DIAGNOSES FROM ANALYTICS.PATIENT_360 WHERE PATIENT_ID IN ({_marks(ids)})",
        ids,
    ):
        dx = {
            normalise(d["description"]): d["description"]
            for d in json_value(r["active_diagnoses"]) or []
        }
        out[r["patient_id"]] = {
            "name": r["full_name"],
            "age": int(r["age_years"]),
            "sex": r["sex"],
            "dx": dx,
            "rx": {},
            "labs": {},
        }
    for r in run(
        f"SELECT PATIENT_ID, COALESCE(DRUG_NAME, DESCRIPTION) AS DRUG FROM ANALYTICS.CURRENT_MEDICATIONS WHERE PATIENT_ID IN ({_marks(ids)})",
        ids,
    ):
        if r["patient_id"] in out and r["drug"]:
            out[r["patient_id"]]["rx"][normalise(r["drug"])] = r["drug"]
    for r in run(
        "SELECT PATIENT_ID, SHORT_NAME, LATEST_VALUE, UNIT, ABNORMAL_FLAG FROM ANALYTICS.PATIENT_LAB_LATEST "
        f"WHERE PATIENT_ID IN ({_marks(ids)})",
        ids,
    ):
        if r["patient_id"] in out:
            out[r["patient_id"]]["labs"][r["short_name"]] = (
                float(r["latest_value"]),
                r["unit"],
                r["abnormal_flag"],
            )
    return {
        pid: Profile(pid, d["name"], d["age"], d["sex"], d["dx"], d["rx"], d["labs"])
        for pid, d in out.items()
    }


def find_similar(
    role: str,
    patient_id: str,
    limit: int = 5,
    mode: Mode = "blend",
    weight: float = WEIGHT_EMBEDDING,
    statements: list[tuple[str, list[Any], int]] | None = None,
) -> Result | None:
    """The closest of the caller's own patients to this one. None when the patient is not visible to the caller (a
    denied patient looks like a missing one); not `ready` while the patient's vector is still being built."""
    notes = statements if statements is not None else []
    with user_cursor(role) as cur:
        query_ids = [patient_id]
        head = profiles(cur, query_ids, notes)
        if patient_id not in head:
            return None
        sql = (
            "SELECT e.PATIENT_ID, VECTOR_COSINE_SIMILARITY(e.EMBEDDING, q.EMBEDDING) AS COS "
            "FROM ANALYTICS.PATIENT_EMBEDDING e JOIN ANALYTICS.PATIENT_EMBEDDING q ON q.PATIENT_ID = %s "
            f"WHERE e.PATIENT_ID <> %s ORDER BY COS DESC LIMIT {CANDIDATES}"
        )
        near = fetch_all(cur, sql, [patient_id, patient_id])
        notes.append((sql, [patient_id, patient_id], len(near)))
        have_vector = fetch_all(
            cur,
            "SELECT 1 AS OK FROM ANALYTICS.PATIENT_EMBEDDING WHERE PATIENT_ID = %s",
            [patient_id],
        )
        if not have_vector:
            return Result(ready=False, matches=[])
        others = profiles(cur, [r["patient_id"] for r in near], notes) if near else {}
    ranked = [
        compare(head[patient_id], others[r["patient_id"]], float(r["cos"]), mode, weight)
        for r in near
        if r["patient_id"] in others
    ]
    ranked = sorted(
        (m for m in ranked if m.score >= MIN_SCORE), key=lambda m: (-m.score, m.profile.patient_id)
    )
    return Result(ready=True, matches=ranked[:limit], candidates=len(near))
