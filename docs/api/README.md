# API reference

The contract is the code. Routes and models live in `src/medynium_api`, FastAPI generates [openapi.json](openapi.json), and the UI generates its TypeScript types from that file. Interactive docs run at `/docs` when the server is up.

Regenerate after any route or schema change: `poetry run poe openapi`.

## Conventions

- All routes require a session except `POST /auth/login` and `GET /health`.
- Errors: `{ "error": code, "message": text }`. Codes: `not_found`, `unauthorized`, `action_not_allowed`, `agent_unavailable`, `timeout`, plus `not_implemented` and `invalid_request` added in this repo.
- A denied patient returns the same 404 body as a missing one.
- `POST /copilot/ask` and `POST /patients/{id}/safety-review` stream server-sent events.

## Endpoint status

| Endpoint | Slice | Status |
| --- | --- | --- |
| `GET /health` | 0 | Live |
| `POST /auth/login`, `POST /auth/logout`, `GET /me` | 3 | Stub |
| `GET /dashboard`, `/patients`, `/patients/{id}`, `/timeline`, `/labs/{code}/trend`, `/claims` | 3 | Stub |
| `GET /knowledge/search` | 4 | Stub |
| `POST /patients/{id}/safety-review`, `GET /evidence/{answer_id}` | 5 | Stub |
| `POST /copilot/ask` | 6 | Stub |
| `POST /agent/actions` | 7 | Stub |
| `GET /audit` | 8 | Stub |
| `POST /admin/golden-run` | 9 | Stub |
| `GET /dashboard/briefing`, `POST /views/preview`, `POST /views`, `POST /admin/skills/{name}` | 10 | Stub |

Detailed request and response shapes, with examples per endpoint, are the next documentation step and will be added here as each slice is designed.
