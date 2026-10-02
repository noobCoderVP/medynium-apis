# AGENTS.md: medynium-api

Context for every CoCo or Claude Code session in this repo (PLT-01). Read the SRS and the implementation plan for the why; this file is the working rules.

## What this is
FastAPI backend for Medynium: a governed Patient 360 and clinical agent on Snowflake. Decision support on synthetic data only. The UI lives in the sibling repo `medynium-ui` and talks to this API only.

## Commands (Poetry; tasks run through Poe)
- `poetry install`: set up `.venv` in the project
- `poetry run poe dev`: run on http://localhost:8000 (docs at `/docs`)
- `poetry run poe check`: lint, format check, mypy strict, tests. Run before every commit.
- `poetry run poe openapi`: rewrite `docs/api/openapi.json`. Commit it when routes or schemas change; CI fails if it is stale and the UI generates its types from it.

## Layout
- `src/medynium_api/api/routes/`: one module per endpoint group, matching SRS section 4.2
- `src/medynium_api/core/`: config, error contract, session dependency, logging
- `src/medynium_api/schemas.py`: request and response models (the public contract)
- `snowflake/`: idempotent setup SQL, numbered in run order
- `data/`, `knowledge/`: loaders and seed data (raw downloads are gitignored)
- `docs/`: API and database documentation, and `external-dependencies.md`

## Rules that must not be broken
1. **Entitlement first.** A denied patient returns exactly the response of a missing one: 404 `not_found`, same body, similar latency. Never put a patient ID in an error message (SEC-05).
2. **User role, not a service role.** Every Snowflake query for a request runs under that user's own connection and role. No shared account that sees all patients serves requests (SEC-03). No runtime path uses `MED_ADMIN` (SEC-06).
3. **Closed action set.** The agent can only do `open_patient`, `show_timeline`, `run_safety_review`, `pin_evidence`, checked server-side. Anything else is `action_not_allowed` and is audited (SEC-12).
4. **The router is not a security boundary.** Entitlement, allowlist and evidence validation run on every route whatever the router said. The router never sees patient records or document text.
5. **Evidence or nothing.** Every answer statement maps to patient evidence or a source chunk; unbacked statements are dropped by the validator. "No documented consideration found in the indexed sources" is never written as "no risk".
6. **No secrets in the repo.** Only `.env.example`. Never log credentials, keys or patient names.
7. **Errors use `{error, message}`** with codes from `core/errors.py`.
8. **Scripts are idempotent.** Setup SQL and loaders can be re-run on a clean or populated schema.

## Conventions
- Python 3.12, type hints everywhere, mypy strict, ruff for lint and format (line length 100).
- Routes are thin; logic goes in service modules (add `services/` when the first real endpoint lands).
- Tests in `tests/`; every route needs a denial and an unauthenticated case.
- Stubs return 501 `not_implemented` until their slice is built, so the OpenAPI document already shows the full contract.
