# API reference

Status: **Draft for review.** This is the intended contract before development starts. Once approved, the route stubs and schemas in `src/medynium_api` are updated to match, `docs/api/openapi.json` is regenerated, and CI keeps it in sync (ADR-011). Where this differs from the SRS list, see [../architecture/decisions.md](../architecture/decisions.md#changes-to-the-srs).

| Document | Endpoints |
| --- | --- |
| [auth.md](auth.md) | Sign-in, refresh, sign-out, `me`, password change, invitations, user and entitlement admin |
| [patients.md](patients.md) | Dashboard, worklist, Patient 360, medications, labs, timeline, claims, notes, pins |
| [copilot.md](copilot.md) | Copilot ask, safety review, agent actions, evidence |
| [knowledge-audit-admin.md](knowledge-audit-admin.md) | Knowledge search and status, audit, saved views, golden run, health |

## Conventions

| Topic | Rule |
| --- | --- |
| Base | The API serves paths without a prefix (`/patients`). The browser reaches it through the UI proxy at `/api/...`. Examples below use the API form. |
| Format | JSON, UTF-8, `snake_case` fields. |
| Dates | `date`: `2026-10-02`. Instants: ISO 8601 UTC with `Z`, e.g. `2026-10-03T08:42:11Z`. The UI converts to IST. |
| Money | `{ "amount": 18400.00, "currency": "INR" }` in responses; request bodies do not carry money. |
| IDs | Strings with readable prefixes: `P-1042`, `ENC-20931`, `CLM-1024`, `ANS-0001`. |
| Pagination | `limit` (default 50, max 200) and `offset`. Lists return `{ "items": [...], "total": n, "limit": n, "offset": n }`. |
| Unknown fields | Request bodies reject unknown fields with `invalid_request`. |
| Idempotency | Only noted where relevant; reads are safe to retry. |
| Rate limits | `POST /auth/login`: 5 per minute per IP and email. `POST /copilot/ask` and safety review: 10 per minute per user. Over the limit returns `429 rate_limited` with `Retry-After`. |

## Authentication

Cookies set by `POST /auth/login`: `med_access` (15 minutes) and `med_refresh` (7 days, path `/auth`). Both are `HttpOnly`, `Secure` (except on localhost), `SameSite=Lax`. Every request except those marked **Public** needs a valid `med_access`. Every non-GET request must also send `X-Medynium-Client: web`, otherwise `403 forbidden`. Details: [../architecture/security-and-access.md](../architecture/security-and-access.md#3-sign-in-sessions-and-tokens).

An expired access token returns `401 unauthorized`; the UI then calls `POST /auth/refresh` once and retries.

## Errors {#errors}

Every error is `{ "error": code, "message": text }`, optionally with `details` for validation errors. Messages never name a patient and never reveal whether an account exists.

| HTTP | `error` | Used when |
| --- | --- | --- |
| 400 | `invalid_request` | Malformed body, unknown field, bad parameter. `details` lists `{field, problem}`. |
| 401 | `unauthorized` | No or expired session, or wrong credentials (same message for unknown email and wrong password). |
| 403 | `forbidden` | The caller's role cannot use this endpoint (e.g. assistant on admin), or the client header is missing. **Never used for patient resources.** |
| 403 | `action_not_allowed` | An agent action outside the allowlist, or a request to change the clinical record. |
| 404 | `not_found` | The resource does not exist **or the caller is not entitled to it**. Same body and similar latency in both cases (SEC-05). |
| 409 | `conflict` | State conflict, e.g. email already has a pending invite. |
| 422 | `invalid_request` | Validation failure (FastAPI default mapped to our contract). |
| 429 | `rate_limited` | Rate limit hit. |
| 501 | `not_implemented` | Route exists but its slice is not built yet. |
| 503 | `agent_unavailable` | The agent or router could not be reached; the rest of the app keeps working. |
| 504 | `timeout` | An agent run or query exceeded its timeout. |

Example:

```json
{ "error": "not_found", "message": "The requested resource was not found." }
```

## Server-sent events (streams)

Used by `POST /patients/{id}/safety-review` and `POST /copilot/ask`. Send `Accept: text/event-stream` for a stream. With `Accept: application/json` the endpoint runs to completion and returns the final object (used by tests and the golden run).

Frame format: `event: <name>` and `data: <JSON>` separated by a blank line. A comment line `: keepalive` is sent every 15 seconds. Streams are **not resumable**; after a drop, call `GET /evidence/{answer_id}` if an `answer_id` was already received, otherwise retry the request.

| Event | When | `data` |
| --- | --- | --- |
| `route` | After routing (Copilot only) | `{ "route": "safety", "model": "claude-sonnet-4-6", "confidence": 0.86, "reason": "...", "cost_note": "strong model" }` |
| `step` | Each tool call or stage | `{ "step_id": "s2", "label": "Reading current medications", "status": "running" \| "done" \| "failed", "detail": "3 active" }`; the same `step_id` is sent again to update status |
| `action` | An allowlisted action ran | `{ "action": "open_patient", "params": {...}, "status": "done", "result": {...} }` |
| `answer` | Final structured answer | The [answer object](../architecture/ai-layer.md#4-answer-object) |
| `refusal` | `refuse` route | `{ "message": "...", "reason": "prescribing" \| "cross_patient" \| "unlisted_action" \| "record_change", "considerations": [...] }` |
| `error` | Failure | `{ "error": "agent_unavailable", "message": "..." }` |
| `done` | Always last | `{ "audit_id": "AUD-..." }` |

The steps streamed equal the `STEPS` stored in the audit entry for the run (FR-21, AI-12).

## Endpoint summary

Tier and slice are from the implementation plan. **New** marks endpoints not in the SRS list.

| Method and path | Auth | Slice | Notes |
| --- | --- | --- | --- |
| `GET /health` | Public | 0 | Liveness only |
| `GET /health/details` | Admin | 11 | **New** |
| `POST /auth/login` | Public | 3 | |
| `POST /auth/refresh` | Refresh cookie | 3 | **New** |
| `POST /auth/logout` | Session | 3 | |
| `GET /me` | Session | 3 | |
| `POST /auth/password` | Session | 3 | **New** |
| `GET /auth/invites/{token}` | Public | 3 | **New** |
| `POST /auth/invites/accept` | Public | 3 | **New** |
| `POST /admin/invites`, `GET /admin/invites`, `DELETE /admin/invites/{id}` | Admin | 3 | **New** |
| `GET /admin/users`, `GET /admin/users/{id}`, `PATCH /admin/users/{id}` | Admin | 3 | **New** |
| `PUT /admin/users/{id}/entitlements`, `GET /admin/users/{id}/entitlements` | Admin | 3 | **New** |
| `POST /admin/users/{id}/reset-password` | Admin | 3 | **New** |
| `GET /dashboard` | Session | 3 | |
| `GET /dashboard/briefing` | Session | 10 | P1 |
| `GET /patients`, `GET /patients/{id}` | Session | 3 | |
| `GET /patients/{id}/medications`, `/labs`, `/notes`, `/notes/{note_id}` | Session | 3 | **New** |
| `GET /patients/{id}/timeline`, `/labs/{code}/trend`, `/claims` | Session | 3 | |
| `GET/POST/DELETE /patients/{id}/pins` | Session | 7 | **New** |
| `GET /knowledge/search`, `GET /knowledge/status` | Session | 4 | status is **New** |
| `POST /patients/{id}/safety-review` | Session | 5 | SSE |
| `GET /evidence/{answer_id}` | Session | 5 | |
| `POST /copilot/ask` | Session | 6 | SSE |
| `POST /agent/actions` | Session | 7 | |
| `GET /audit` | Session | 8 | |
| `POST /admin/golden-runs`, `GET /admin/golden-runs/{id}`, `GET /admin/golden-runs/latest` | Doctor | 9 | async; replaces `POST /admin/golden-run` |
| `POST /admin/skills/{name}` | Doctor | 10 | P1 |
| `POST /views/preview`, `POST /views`, `GET /views` | Session | 10 | P1 |

## Implementation status and as-built differences (stages 0 to 4)

Built and tested against the live account: everything in `auth.md`, `patients.md` and `knowledge-audit-admin.md` except the golden-run and skills endpoints; `GET /evidence/{answer_id}`; `POST /patients/{id}/safety-review`; `POST /copilot/ask`; `POST /agent/actions`; `/health` and `/health/details`.

Still stubs or not built: `POST /admin/golden-runs`, `GET /admin/golden-runs/*`, `POST /admin/skills/{name}`. `docs/api/openapi.json` was regenerated on 2026-10-03 and the UI types were generated from it.

Differences from the drafts above:

| Area | As built |
| --- | --- |
| Streams | The entitlement check runs **before** a stream opens, so a denied or missing patient is a plain `404` (same body and similar latency), never a stream with an error event. `done` is always the last event and carries the `audit_id`. |
| JSON mode | `POST /patients/{id}/safety-review` returns the answer object. `POST /copilot/ask` returns `{routes, actions, answer, refusal, steps, audit_id}`. |
| Route event | Adds `reason`, `fallback` (router failed, handled as a question) and `escalated` (low confidence went up to the careful route). |
| `cost_note` values | `no model call`, `router only, no generating model`, `rule guard, no model call`, `strong model`, `Cortex Analyst`. |
| Answer kinds | `SAFETY`, `CHANGED`, `MEDS`, `LABS`, `UTIL`, `SUMMARY`, `ANALYST`, `KNOWLEDGE`. |
| Knowledge search | The response adds `resolved` (brand or alias to generic), `message` (shown when nothing matches: "No matching section in the indexed sources.") and `conflicts` (drug and section pairs with differing sources). Results carry `snippet` and `text`. |
| Agent actions | `open_patient` with a `name_query` that matches several entitled patients returns `409 conflict` with candidates in `details` (at most five), or asks to narrow when more match. A name that matches none, or only patients the caller cannot see, returns the standard `404`. `409` and `403 action_not_allowed` are both audited. |
| Invites | `GET /auth/invites/{token}` returns `kind` (`INVITE` or `PASSWORD_RESET`). The reset link from `POST /admin/users/{id}/reset-password` is accepted through `POST /auth/invites/accept`, which then sets the new password instead of creating a user. |
| Pins | `POST` accepts an `Idempotency-Key` header; a repeat returns the same pin. |
| Cookies | `med_refresh` is scoped to the path in the setting `REFRESH_COOKIE_PATH`. It defaults to `/auth` for callers that reach the API directly; behind the UI's `/api` proxy it must be `/api/auth`, otherwise the browser never sends it and sessions cannot renew. |
| Errors | Adds `internal_error` (500, generic body; the trace is logged with the request id). Every response carries `X-Request-Id`. Non-public responses carry `Cache-Control: private, no-store`. |
| Rate limits | Login: 5 per minute per IP and per email. Ask and safety review: 10 per minute per user. |
| CSRF | Every non-GET request without `X-Medynium-Client: web` is a `403 forbidden`, before routing. |
| Health | `/health` returns only `{status, version}`. `/health/details` (admin) returns Snowflake reachability, warehouse state, the service role, Cortex model names, the safety path and audit-write status. |
| Dashboard | The ED flag reads "ED visit 2 Oct" (a date, not "yesterday"). `recent_changes.labs` is a top ten across the caller's patients, abnormal first. |
| Patients | `q` also matches a patient's main diagnoses, so "kidney" finds kidney patients. |
