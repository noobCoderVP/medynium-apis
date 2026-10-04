"""Compare the three similar-patient scoring modes (production plan P5.5). Run: python scripts/eval_similar.py

THE LIMIT, STATED FIRST. There is no clinician-labelled ground truth here, so "relevant" is a PROXY: a neighbour counts as
relevant when its set of broad condition families (diabetes, kidney disease, hypertension, heart disease, ...) overlaps
the query's by at least half. That proxy comes from keywords on diagnosis names, not from the features the scores use,
so it is not circular, but it is still not a clinical judgement. The numbers say which mode ranks best against that proxy
and nothing more. A real evaluation needs a clinician to mark the top results for about twenty patients; until then the
default weight stays at the documented 0.5 and no clinical accuracy is claimed.

Writes docs/quality/similar-eval.md and prints the same table."""

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from medynium_api.core.config import get_settings  # noqa: E402
from medynium_api.core.ids import role_for_user  # noqa: E402
from medynium_api.core.similar import CANDIDATES, Mode, Profile, compare, profiles  # noqa: E402
from medynium_api.core.snowflake.queries import fetch_all  # noqa: E402
from medynium_api.core.snowflake.role_session import service_cursor, user_cursor  # noqa: E402

DOCTOR_EMAIL = "sharma@demo.medynium"
SAMPLE = 80
K = 5
FAMILIES = {
    "diabetes": ("diabet", "glycaemi", "hyperglyc"),
    "kidney": ("kidney", "renal", "nephro"),
    "hypertension": ("hypertens", "blood pressure"),
    "heart": ("cardi", "heart", "coronary", "ischemic", "myocard", "angina", "atrial"),
    "respiratory": ("asthma", "copd", "bronch", "pulmon", "respirat"),
    "anaemia": ("anemi", "anaemi"),
    "lipids": ("cholesterol", "lipid", "dyslipid"),
    "thyroid": ("thyroid",),
    "mental": ("depress", "anxiety", "schizo", "bipolar"),
}


def families(profile: Profile) -> set[str]:
    names = " ".join(profile.diagnoses.values()).lower()
    return {fam for fam, words in FAMILIES.items() if any(w in names for w in words)}


def relevant(query: Profile, other: Profile) -> bool:
    a, b = families(query), families(other)
    return bool(a) and len(a & b) / len(a | b) >= 0.5


def main() -> None:
    settings = get_settings()
    with service_cursor() as cur:
        user = fetch_all(
            cur, "SELECT USER_ID FROM SECURITY.APP_USER WHERE EMAIL = %s", (DOCTOR_EMAIL,)
        )[0]
    role = role_for_user(user["user_id"])
    precision: dict[Mode, list[float]] = {"blend": [], "structured": [], "embedding": []}
    evaluated = 0
    with user_cursor(role) as cur:
        ids = [
            r["patient_id"]
            for r in fetch_all(
                cur, "SELECT PATIENT_ID FROM ANALYTICS.PATIENT_EMBEDDING ORDER BY PATIENT_ID"
            )
        ]
        step = max(1, len(ids) // SAMPLE)
        for pid in ids[::step][:SAMPLE]:
            notes: list[tuple[str, list, int]] = []
            head = profiles(cur, [pid], notes).get(pid)
            if head is None or not families(head):
                continue
            near = fetch_all(
                cur,
                "SELECT e.PATIENT_ID, VECTOR_COSINE_SIMILARITY(e.EMBEDDING, q.EMBEDDING) AS COS "
                "FROM ANALYTICS.PATIENT_EMBEDDING e JOIN ANALYTICS.PATIENT_EMBEDDING q ON q.PATIENT_ID = %s "
                f"WHERE e.PATIENT_ID <> %s ORDER BY COS DESC LIMIT {CANDIDATES}",
                [pid, pid],
            )
            others = profiles(cur, [r["patient_id"] for r in near], notes)
            evaluated += 1
            for mode in precision:
                ranked = sorted(
                    (
                        compare(
                            head,
                            others[r["patient_id"]],
                            float(r["cos"]),
                            mode,
                            settings.similar_weight_embedding,
                        )
                        for r in near
                    ),
                    key=lambda m: -m.score,
                )[:K]
                precision[mode].append(sum(relevant(head, m.profile) for m in ranked) / K)
    lines = [
        "# Similar-patient scoring: proxy evaluation",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC. {evaluated} query patients, top {K} each, candidates {CANDIDATES} per query.",
        "",
        "**Read this first.** There is no clinician-labelled ground truth. A neighbour counts as relevant when its broad condition families overlap the query's by at least half (families come from keywords on diagnosis names). This ranks the three scoring modes against that proxy. It is not clinical accuracy and no clinical claim is made from it.",
        "",
        "| Scoring mode | Precision at 5 (proxy) |",
        "| --- | --- |",
    ]
    for mode, values in precision.items():
        lines.append(
            f"| {mode} | {sum(values) / len(values):.3f} |" if values else f"| {mode} | n/a |"
        )
    lines += [
        "",
        f"Weight on embedding similarity in the blend: {settings.similar_weight_embedding}.",
    ]
    out = ROOT / "docs" / "quality" / "similar-eval.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
