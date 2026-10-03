"""Routing evaluation (FR-23, 07 section 4.2): run the router over evals/routing_set.json and report accuracy.

Usage: python scripts/eval_routing.py   (calls the router model, so it needs the Snowflake account)
Writes docs/evals/routing-report.json and routing-report.md, failures included.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

from medynium_api.core.config import get_settings
from medynium_api.features.copilot.routing import decide

ROOT = Path(__file__).resolve().parent.parent
settings = get_settings()
cases = json.loads((ROOT / "evals" / "routing_set.json").read_text(encoding="utf-8"))["cases"]
results, per_group, confusion = [], defaultdict(lambda: [0, 0]), Counter()
for case in cases:
    decision = decide(settings, case["q"], case["screen"], case["patient_id"], case["history"])
    actual = [s.route for s in decision.steps]
    ok = actual == case["expect"] or actual in case.get("accept", [])
    per_group[case["group"]][0] += ok
    per_group[case["group"]][1] += 1
    if not ok:
        confusion[f"{'+'.join(case['expect'])} -> {'+'.join(actual)}"] += 1
    results.append(
        {
            **case,
            "actual": actual,
            "pass": ok,
            "fallback": decision.fallback,
            "escalated": decision.escalated,
        }
    )
passed = sum(r["pass"] for r in results)
summary = {
    "total": len(results), "passed": passed, "accuracy": round(passed / len(results), 3),
    "hard_passed": sum(r["pass"] for r in results if r["hard"]), "hard_total": sum(r["hard"] for r in results),
    "per_route": {g: f"{a}/{b}" for g, (a, b) in per_group.items()}, "confusion": dict(confusion),
}  # fmt: skip
out = ROOT / "docs" / "evals"
out.mkdir(parents=True, exist_ok=True)
(out / "routing-report.json").write_text(
    json.dumps({"summary": summary, "results": results}, indent=1), encoding="utf-8"
)
lines = [
    "# Routing evaluation", "", f"Router model: `{settings.router_model}`. {passed}/{len(results)} passed ({summary['accuracy']:.0%}); "
    f"hard cases {summary['hard_passed']}/{summary['hard_total']}.", "", "| Route | Passed |", "| --- | --- |",
    *[f"| {g} | {v} |" for g, v in summary["per_route"].items()], "", "## Failures", "",
    *[f"- `{r['q']}` expected {r['expect']}, got {r['actual']}" for r in results if not r["pass"]],
    "", "## Confusion pairs", "", *[f"- {k}: {v}" for k, v in confusion.items()],
]  # fmt: skip
(out / "routing-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=1))
