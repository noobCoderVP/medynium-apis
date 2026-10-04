# quality

Shows the latest stored golden run to admins (Q-6, FR-11).

- Endpoint: `GET /admin/golden-runs` (admin only; 401 without a session, 403 for non-admins).
- Runs are produced by `poetry run python scripts/eval_golden.py --set golden --store`, which writes
  `ANALYTICS.GOLDEN_RUN` / `GOLDEN_RESULT` as the admin's own role. This feature never starts a run or calls a model.
- May import: `core/` only.
