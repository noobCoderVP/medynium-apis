---
name: golden-run
description: Run the Medynium golden, injection, routing and retrieval evaluation sets against the live account and report failures honestly. Use before a release or after changing prompts, routing or the corpus.
---

1. Pin the date: `DEMO_AS_OF_DATE=2026-10-02` (the seeded data is dated to it).
2. `poetry run python scripts/eval_golden.py --set all --store` writes `docs/quality/golden-report.md`, `injection-report.md` and saves the golden run for `GET /admin/golden-runs`.
3. `poetry run python scripts/eval_routing.py` for the routing set; `poetry run python knowledge/eval/run_eval.py` for retrieval.
4. A failing case is rerun alone with `--only ID --repeat 3` to separate a flake from a defect. Report both numbers; never relabel a failure as a pass.
5. Do not edit expectations to make a case pass; fix the code, or state the deviation in the report.
