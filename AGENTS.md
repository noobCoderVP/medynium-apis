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
- `src/medynium_api/features/<name>/`: one self-contained folder per endpoint group (SRS 4.2): `router.py` (thin), `schemas.py` (that feature's public contract), `service.py` (logic), `repository.py` (the only place that runs Snowflake SQL), `README.md` (context card), tests
- `src/medynium_api/router.py`: mounts every feature router
- `src/medynium_api/core/`: config, error contract, session dependency, logging. Shared infrastructure only; never imports a feature
- `snowflake/`: idempotent setup SQL, numbered in run order
- `data/`, `knowledge/`: loaders and seed data (raw downloads are gitignored)
- `docs/`: API and database documentation, and `external-dependencies.md`

## Rules that must not be broken
1. **Entitlement first.** A denied patient returns exactly the response of a missing one: 404 `not_found`, same body, similar latency. Never put a patient ID in an error message (SEC-05).
2. **User role, not a service role.** Every Snowflake query for a request runs under that user's own connection and role. No shared account that sees all patients serves requests (SEC-03). No runtime path uses `MED_ADMIN` (SEC-06).
3. **Closed action set.** The agent can only do `open_patient`, `show_timeline`, `run_safety_review`, `pin_evidence`, checked server-side. Anything else is `action_not_allowed` and is audited (SEC-12). Writes are never an action: a change to the record is a proposal the clinician approves (see `features/copilot/README.md`).
4. **The router is not a security boundary.** Entitlement, allowlist and evidence validation run on every route whatever the router said. The router never sees patient records or document text.
5. **Evidence or nothing.** Every answer statement maps to patient evidence or a source chunk; unbacked statements are dropped by the validator. "No documented consideration found in the indexed sources" is never written as "no risk".
6. **No secrets in the repo.** Only `.env.example`. Never log credentials, keys or patient names.
7. **Errors use `{error, message}`** with codes from `core/errors.py`.
8. **Scripts are idempotent.** Setup SQL and loaders can be re-run on a clean or populated schema.

## Conventions
- Python 3.12, type hints everywhere, mypy strict, ruff for lint and format (line length 100).
- Routes are thin. Dependency direction is `router -> service -> repository -> Snowflake`, never backwards.
- Add `service.py` and `repository.py` to a feature when its slice is built; stubs only need `router.py`.
- Tests in `tests/`; every route needs a denial and an unauthenticated case.
- Stubs return 501 `not_implemented` until their slice is built, so the OpenAPI document already shows the full contract.

## Modularization (enforced by `tests/test_architecture.py`)
- A feature never imports another feature. Shared code goes in `core/`, and only when two features need it.
- Only `repository.py` (and `core/`) imports `snowflake`. Routers never import a repository.
- Files stay under 300 lines; split by responsibility before they grow.
- Each feature folder carries a short `README.md` card: purpose, endpoints, requirement IDs, what it may import. Keep it current so one folder can be handed to an AI session without the rest of the repo.

## Definition of done for a slice
1. `poetry run poe check` passes and the `poetry run poe openapi` output is committed.
2. Denial (404) and unauthenticated (401) tests exist for every new route.
3. The hard rules above still hold, and the feature README card is updated.
4. The UI types still generate (`npm run api:types` in `medynium-ui`).

## Don't
- Don't add a dependency without asking. Don't hand-edit `docs/api/openapi.json` (a hook blocks it).
- Don't query Snowflake from a router or service, or with a shared role.

## Project skills (`.claude/skills/`)
- `new-api-endpoint`: add or implement an endpoint inside a feature folder
- `slice-done`: run the done checklist and tick the implementation-plan tracker
