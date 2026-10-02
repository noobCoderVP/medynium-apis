# medynium-api

FastAPI backend for Medynium, a governed Patient 360 and clinical agent on Snowflake. Synthetic data only; decision support, not diagnosis.

Sibling repo: `medynium-ui` (Next.js).

## Quick start

Requirements: Python 3.12, [Poetry](https://python-poetry.org/) 2.x.

```bash
poetry install
cp .env.example .env          # Windows: copy .env.example .env
poetry run poe dev            # http://localhost:8000/docs
```

`/health` works with no Snowflake credentials. Every other route needs a session and currently answers `401`, or `501 not_implemented` once signed in, until its slice is built.

## Daily commands

| Command | What it does |
| --- | --- |
| `poetry run poe dev` | Run with reload |
| `poetry run poe check` | Lint, format check, mypy strict and tests |
| `poetry run poe format` | Auto-format with ruff |
| `poetry run poe openapi` | Regenerate `docs/api/openapi.json` for the UI |
| `poetry run pre-commit install` | Install git hooks (ruff, mypy, secret scanning) |

If your shell has another project's virtualenv active, run `deactivate` (or unset `VIRTUAL_ENV`) first, or Poetry will install into that environment instead of `.venv`.

## Deploy

Render builds the `Dockerfile` through `render.yaml` (New > Blueprint). Set the secrets marked `sync: false` in the dashboard. CI (`.github/workflows/ci.yml`) runs the checks and a Docker build on every push. Full variable list: [docs/external-dependencies.md](docs/external-dependencies.md).

## Docs

- [External dependencies and what we need](docs/external-dependencies.md)
- [API reference](docs/api/README.md)
- [Database](docs/database/README.md)
- [AGENTS.md](AGENTS.md): working rules for AI sessions and contributors
