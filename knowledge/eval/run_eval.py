"""Retrieval evaluation (K-8): recall@3, recall@5, MRR, negatives and per-query misses.

Runs the real KnowledgeService against the live index as a seeded doctor. Exit code 1 below the recorded target.
Usage: python knowledge/eval/run_eval.py [--min-cosine 0.45]
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from medynium_api.core.config import get_settings  # noqa: E402
from medynium_api.core.cortex import search_client  # noqa: E402
from medynium_api.core.session import Session  # noqa: E402
from medynium_api.core.snowflake.queries import fetch_one  # noqa: E402
from medynium_api.core.snowflake.role_session import service_cursor  # noqa: E402
from medynium_api.features.knowledge.service import KnowledgeService  # noqa: E402

TARGETS = {"recall@3": 0.85, "recall@5": 0.90, "mrr": 0.70, "negatives": 1.0}


def doctor() -> Session:
    with service_cursor() as cur:
        row = fetch_one(
            cur, "SELECT USER_ID FROM SECURITY.APP_USER WHERE EMAIL = 'sharma@demo.medynium'"
        )
    assert row, "seed the demo users first"
    return Session(row["user_id"], "DOCTOR", True, "eval", 1, datetime.now(UTC))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-cosine", type=float, default=search_client.MIN_COSINE)
    args = parser.parse_args()
    search_client.MIN_COSINE = args.min_cosine
    queries = [  # the first 25 drugs, then the India-focused additions (Phase 4)
        q
        for name in ("retrieval_set.yaml", "retrieval_set_india.yaml")
        for q in yaml.safe_load((Path(__file__).parent / name).read_text(encoding="utf-8"))[
            "queries"
        ]
    ]
    service = KnowledgeService(get_settings())
    session = doctor()

    ranks: list[int | None] = []
    negatives_ok, negatives = 0, 0
    misses: list[str] = []
    for item in queries:
        result = service.search(session, item["q"], None, None, 5)
        if item["kind"] == "negative":
            negatives += 1
            top = max((c.score for c in result.items), default=0.0)
            if not result.items:
                negatives_ok += 1
            else:
                misses.append(
                    f"NEGATIVE returned {len(result.items)} chunks (top {top:.2f}): {item['q']}"
                )
            continue
        sections = set(item.get("sections", []))
        rank = next(
            (
                i
                for i, c in enumerate(result.items, start=1)
                if c.drug == item["drug"] and (not sections or c.section in sections)
            ),
            None,
        )
        ranks.append(rank)
        if rank is None or rank > 3:
            got = [(c.drug, c.section, c.score) for c in result.items[:3]]
            misses.append(f"MISS rank={rank} {item['q']!r} want {item['drug']}; got {got}")

    n = len(ranks)
    report = {
        "recall@3": sum(1 for r in ranks if r and r <= 3) / n,
        "recall@5": sum(1 for r in ranks if r and r <= 5) / n,
        "mrr": sum(1 / r for r in ranks if r) / n,
        "negatives": negatives_ok / negatives if negatives else 1.0,
    }
    print(f"queries: {n} positive, {negatives} negative; min cosine {args.min_cosine}")
    for key, target in TARGETS.items():
        print(
            f"{key}: {report[key]:.3f} (target {target}) {'PASS' if report[key] >= target else 'FAIL'}"
        )
    print("\n".join(misses) or "no misses")
    sys.exit(0 if all(report[k] >= t for k, t in TARGETS.items()) else 1)


if __name__ == "__main__":
    main()
