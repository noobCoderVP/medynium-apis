# CoCo CLI evidence

What CoCo CLI and Claude Code sessions are set up to do in this repo, where the proof lives, and what to re-run.
Nothing here is claimed unless a command below reproduces it.

## Skills (`.claude/skills/`)

| Skill | Purpose | Backed by |
| --- | --- | --- |
| `new-api-endpoint` | Add an endpoint inside one feature folder, with denial and 401 tests | `tests/test_architecture.py`, `tests/test_api_contract.py` |
| `slice-done` | Run the done-when checklist and tick the plan tracker | `poe check`, `poe openapi` |
| `access-check` | Re-prove the entitlement chain binds SQL, Cortex Analyst and the assistant | `tests/integration/test_access_sql.py`, golden group `access` |
| `evidence-audit` | Audit evidence, negation, refusal, gap and injection behaviour | `tests/test_negation_guard.py`, golden and injection sets |

## Hooks (`.claude/hooks/`, wired in `.claude/settings.json`)

| Hook | Event | Effect |
| --- | --- | --- |
| `guard.mjs` | PreToolUse on Edit and Write | Blocks hand edits to `docs/api/openapi.json` (generated), `.env` files and `.pem`/`.p8`/`.key` files |
| `format.mjs` | PostToolUse on Edit and Write | Formats edited Python files with ruff |

## Measured results

| Evidence | Where | Reproduce |
| --- | --- | --- |
| Golden set (25 cases incl. refusal, gap, access, negation) | `docs/quality/golden-report.md`, `golden-stability-report.md` | `poetry run poe eval:golden` |
| Prompt-injection set (12 cases) | `docs/quality/injection-report.md` | `poetry run poe eval:injection` |
| Routing set (47 prompts) | `docs/evals/routing-report.md` | `poetry run poe eval:routing` |
| Latency and cost notes | `docs/quality/timing-report.md` | `poetry run python scripts/eval_timing.py` |
| Access and safety matrix | `docs/quality/access-and-safety-matrix.md` | `/access-check` |
| Data provenance | `data/PROVENANCE.md` | `poetry run poe provenance` |

The three negation cases (G23 to G25) and the polarity rule in both prompts were added after reviewing
other entries for the same problem: search that matches a topic but not its polarity ("mother had X"
versus "no history of X"). Their results appear in the golden report after the next live run.

## Session logs

Save CoCo CLI session logs under `docs/media/coco-logs/` (see `docs/media/README.md`) and list each
run here with its date, command and what it caught.

| Date | Session | Skill or command | What it caught |
| --- | --- | --- | --- |
| _add after each run_ | | | |
