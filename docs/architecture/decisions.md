# Decision log

Status key: **Accepted** (decided), **Proposed** (my recommendation, needs your confirmation), **To validate** (depends on a spike).

## Decisions

### ADR-001: Snowflake is the only datastore. Accepted
Users, invites, sessions, entitlements, audit, answers and clinical data all live in Snowflake. No Postgres or Redis.
- **Why:** you asked for it; one platform, fewer vendors and secrets, matches the original plan and keeps governance in one place.
- **Costs:** the first request after the warehouse suspends takes a few seconds; each query is slower than an OLTP database; auth writes consume small amounts of credit.
- **Mitigations:** auth lookups touch tiny tables; access tokens are verified without a database call; refresh is every 15 minutes; optional warm-up call before a demo.

### ADR-002: Real accounts, admin-invite onboarding, argon2id passwords in Snowflake tables. Accepted
No managed identity provider. Admins invite users and assign patients. MFA is out of scope for the hackathon and is the first hardening step. Details in [security-and-access.md](security-and-access.md).
- **Why:** you chose Snowflake-backed accounts and admin invites.
- **Cost:** we own password, lockout and session code; it is small and has explicit tests.

### ADR-003: One service identity plus a Snowflake role per app user. Accepted (spike S-A passed)
`MED_API` authenticates by key pair and runs `USE ROLE U_<user_id>` per request. Row access policies use `IS_ROLE_IN_SESSION` against `SECURITY.PATIENT_ENTITLEMENT`.
- **Alternatives:** (a) a Snowflake **user** per app user, with a key pair provisioned at invite time (more secret handling, same policy model); (b) one shared role with API-side filtering only (violates SEC-02); (c) a session variable read by the policy (not relied on until proven supported).
- **Why this one:** scales to real accounts without a key pair per person, and keeps access enforcement inside Snowflake.
- **Validated 2026-10-03** (see [spikes.md](spikes.md)): policies, Analyst and Agent all honour the role. Per-user roles are granted to the service **user**, not to the `MED_API` role.
- **Original gate:** Slice 2 spike ([validation steps](security-and-access.md#validation-spike)). If it fails, fall back to (a), then to the backend-runs-SQL fallback for the AI layer.

### ADR-004: Stateless access token plus rotating refresh token. Accepted
15-minute JWT in an `HttpOnly` cookie, 7-day rotating refresh token hashed in `SECURITY.AUTH_SESSION`, reuse detection.
- **Why:** avoids a Snowflake query on every request.
- **Trade-off:** up to 15 minutes before a disabled user's access token expires; closable with a short cache of the token version.

### ADR-005: Invites return a link, no email delivery. Proposed
`POST /admin/invites` returns a one-time accept link for the admin to share. An email provider (Resend, SMTP) can be added later behind the same endpoint.
- **Why:** no new external service or domain verification for the hackathon.

### ADR-006: UI proxies the API same-origin. Accepted
`next.config.ts` rewrites `/api/*` to `BACKEND_URL`.
- **Why:** first-party cookies, no CORS or third-party cookie issues.
- **Risk:** SSE through the proxy must be verified early (R-3). Fallback: custom domain, direct calls with CORS and a parent-domain cookie.

### ADR-007: Hosting on Google Cloud Run (API and UI), asia-south1. Accepted (revised from Render and Vercel)
Both services on Cloud Run with minimum one instance, so the `/api` proxy and SSE run inside GCP and there is no cold start in a live demo. Snowpark Container Services is not used. `render.yaml` is retired when the GCP deployment lands (Stage 8). Needs a GCP project from you.

### ADR-008: Precompute analytics at load time. Accepted
`PATIENT_360`, `PATIENT_TIMELINE`, `UTILIZATION`, `CURRENT_MEDICATIONS` and `DASHBOARD_WORKLIST` are built by scripted `CREATE TABLE AS` at load, not dynamic tables.
- **Why:** page loads do no joins and no AI; no refresh cost; data is static.
- **Consequence:** an "as of" date is a setting (`DEMO_AS_OF_DATE`), and change flags are relative to it.

### ADR-009: Answers and their evidence are stored in `ANALYTICS`, not `KNOWLEDGE`. Accepted
The SRS lists `EVIDENCE` under `KNOWLEDGE`. Evidence rows reference patient records, so they need the row access policy. `KNOWLEDGE` stays strictly public documents (SEC-04). See `ANALYTICS.ANSWER` and `ANSWER_EVIDENCE`.

### ADR-010: India localisation happens at load time. Accepted
Names, places, PIN codes and phone formats are replaced from a seeded generator; USD amounts are converted to INR at a fixed documented rate; the UI formats with `en-IN` and IST. Details in [../database/data-loading.md](../database/data-loading.md).

### ADR-011: The code is the API contract; markdown is for humans. Accepted
FastAPI generates `docs/api/openapi.json`; the UI generates its types from it; CI fails if the file is stale. The markdown in `docs/api/` explains behaviour and examples and must stay consistent with it.

### ADR-012: Cost-effective models only. Accepted
No Opus-class models. Router: `llama3.1-8b`. Strong route: `claude-sonnet-4-6`. Verified available on the account (Azure Central India).

### ADR-013: Audit writes are synchronous for denials and agent actions. Proposed
Inserted before the response completes so a crash cannot lose them. **Amended 2026-10-03:** opening a patient (`GET /patients/{id}`) now writes a `VIEW_PATIENT` row, so "who looked at this chart?" can be answered. Other read-only list and tab views are still not audited, to keep volume down; revisit if a privacy review asks for per-tab access logs. Users still see only their own rows; an organisation-wide auditor view is not built.
- **Cost:** roughly one extra Snowflake round trip per audited request.

### ADR-014: UI on Cloud Run with the `/api` rewrite kept. Accepted
Same-origin cookies; SSE runs server to server inside GCP. See build-plan/08.

### ADR-015: Safety route is an evidence-pack path by default; Cortex Agent behind a setting. Accepted
Spike S-B measured about 15 s for a trivial agent run, too slow for the 20 s target. Default: deterministic SQL under the user's role, Cortex Search, one strong-model `COMPLETE` call with compact structured output, then the validator. The Cortex Agent path (`SAFETY_PATH=agent`) stays available and is built after the default is green. See [spikes.md](spikes.md).

### ADR-016: Prompts live in versioned files, hashed into every audit row. Accepted
Makes an answer reproducible (NFR-05). Files under `src/medynium_api/features/copilot/prompts/`.

### ADR-017: No mock layer in the UI. Accepted
Development speed. Build against the real API; before a slice lands pages show their error or agent-unavailable state.

### ADR-018: Design direction approved before prototype styling is ported. Accepted
The UI is built on tokens in `globals.css`, so restyling is a token change.

### ADR-019: Setup connects with a personal access token as the admin user, then drops to `MED_ADMIN`. Accepted
`scripts/db.py bootstrap` uses `ACCOUNTADMIN` once; every other script uses `MED_ADMIN`. The token should be revoked after the build.

## Changes to the SRS

| SRS says | This design | Why |
| --- | --- | --- |
| One Snowflake user per app user, key pair each (BRD SEC-01, SRS 3.1) | One service user plus a role per app user (ADR-003) | Real accounts; avoids a key pair per person |
| Seeded users `SHARMA_DR`, `CLINIC_ASST`, `SECOND_DR` with passwords | Real accounts through invites; the three are seeded as ordinary users for the demo | Real login |
| `EVIDENCE` in `KNOWLEDGE` | `ANSWER` and `ANSWER_EVIDENCE` in `ANALYTICS` | ADR-009 |
| API list (SRS 4.2) | Adds invites, user and entitlement admin, refresh, password change, medications, labs, notes, pins, knowledge status, golden-run results, health details | Needed by real accounts and by the Medications, Labs and Notes tabs |
| `POST /patients/{id}/safety-review` returns `answer_id` | Streams over SSE and ends with an event carrying the answer (and `answer_id`); a JSON mode exists for tests | Plan section 5, Slice 5 |
| Error codes: `not_found`, `unauthorized`, `action_not_allowed`, `agent_unavailable`, `timeout` | Adds `forbidden`, `invalid_request`, `rate_limited`, `conflict`, `not_implemented` | Real login and admin |
| `/health` reports role, database, warehouse, agent | Public `/health` is liveness only; details moved to admin-only `/health/details` | Avoid leaking configuration to anonymous callers |

## Open questions

| # | Question | My default |
| --- | --- | --- |
| Q1 | Is an admin a flag on a doctor (`IS_ADMIN`) or a separate role? | A flag on a doctor |
| Q2 | Should assistants be able to run the safety review? | Yes, for entitled patients; same rules as a doctor |
| Q3 | Rupee conversion rate | ₹85 per USD, fixed and documented |
| Q4 | Do the NLEM and ICMR documents go into the knowledge base? | P1 only, after a license check; FDA labels first |
| Q5 | Close the 15-minute revocation gap with a token-version cache? | No for the demo; yes if you want immediate disable |

## Build log: deviations and findings (stages 0 to 4)

| # | Finding | Decision or change |
| --- | --- | --- |
| 1 | Per-user roles must be granted to the service **user**, not the `MED_API` role, or `MED_API` inherits every user's access | `GRANT ROLE U_x TO USER MED_API_SVC`; `DEFAULT_SECONDARY_ROLES = ()` |
| 2 | A Snowflake table can carry **one** row access policy | Three policies: `PATIENT_RAP`, `PATIENT_OWN_RAP` (own rows and still entitled; a null patient belongs to the owner), `OWN_RAP` (audit, own rows only) |
| 3 | The Cortex Agent took about 15 s for a trivial run | ADR-015: evidence-pack path by default; agent path not built yet |
| 4 | Cortex Analyst returns SQL and never executes it | The API runs it under the user's role after a guard: one read-only statement that names the patient in scope |
| 5 | Synthea claims: one encounter can have 1 to 3 claims; amounts live in claim transactions (`AMOUNT` for charges, `PAYMENTS` for payments); status is always CLOSED | `CLAIM` rolls up billed, approved (payments minus the patient's share) and outstanding; statuses `APPROVED`, `PARTIAL`, `SUBMITTED`, `SELF_PAY` |
| 6 | US prices converted to rupees read 15 to 20 times too high | `INDIA_PRICE_FACTOR` 0.06 on top of 85 per USD; an ED visit averages about 18,000 INR |
| 7 | Synthea "conditions" include findings and situations (employment, social) | Only `(disorder)` rows are loaded as diagnoses |
| 8 | A plain openFDA query returns combination products | Single-ingredient labels only, latest effective date, saved raw |
| 9 | Free text for a drug outside the corpus still scored 0.39 to 0.49 | Unresolved text must score 0.50; a drug that is named or resolved filters first and needs only 0.30. Eval: recall@3, recall@5, MRR all 1.0, negatives 100% |
| 10 | The model stretched relevance for S2, S4 and S5 (normal values, boilerplate warnings) | Prompt tightened **and** a code rule: an `ai_synthesis` must cite an abnormal lab or two interacting medicines; supporting statements survive only if a conclusion cites them |
| 11 | "Open the kidney patient" matches 40 of Sharma's patients | Ambiguity returns candidates, or asks to narrow past five; the agent never guesses. The demo phrase is "open Rahul Patel" |
| 12 | Hooks block editing `.env` and key files | Defaults in settings (`SNOWFLAKE_API_USER`, key path `~/.medynium/keys/med_api_svc.p8`); keys generated by script outside the repo |
| 13 | A dashboard "ED visit yesterday" cannot be derived from an as-of date | The flag reads "ED visit 2 Oct" |
| 14 | `CREATE OR REPLACE` on the search service would rebuild it on every full apply | `IF NOT EXISTS`; to rebuild, drop it explicitly |

### Open at the end of stage 4: status after stages 5 to 7

- ~~Bug: the batched evidence insert fails when a column is entirely NULL.~~ Fixed: values are cast with `::VARCHAR` before `TRY_*`; the `lookup` and `changed` live tests pass.
- ~~The routing set and its accuracy report are not written.~~ Written: `evals/routing_set.json` (35 cases), `docs/evals/routing-report.md`.
- The Cortex Agent path (A-6) is still not built. The dashboard briefing (A-13) is built (rules over the dashboard data, no model call).
- ~~`openapi.json` and the UI types are stale.~~ Regenerated on 2026-10-03; the UI builds on them.
- The personal access token in `.env` should be revoked once setup is finished.

## Build log: findings and decisions (stages 5 to 7)

| # | Finding | Decision or change |
| --- | --- | --- |
| 15 | **The refresh cookie could never reach the API from the browser.** It was scoped to `/auth`, but the browser calls the API under the UI's `/api` proxy, so `/api/auth/refresh` never received it and every session would have ended after 15 minutes | New setting `REFRESH_COOKIE_PATH` (default `/auth`, so direct callers and tests are unchanged). Deployments behind the UI proxy set `/api/auth`; `.env.example` says so. Integration tests pin `/auth`. Logout clears the cookie on the same path |
| 16 | The Next 16 request gate (`proxy.ts`) cannot see the refresh cookie (wrong path), only `med_access`, which lasts 15 minutes | The gate only keeps visitors with no session cookie off workstation pages. A visitor whose access cookie lapsed lands on sign-in, which first tries a silent refresh and returns them to where they were. `next` is only followed for same-origin paths |
| 17 | The "what changed" answer quoted the first 200 characters of each note as a patient-fact statement, so the S5 injected text could appear as a statement (found by the new injection set, case I10) | Notes appear in generated statements by title only. The note body stays in the Notes tab as plain text |
| 18 | The router sent "is anything worth a second look given her results?" to Cortex Analyst instead of the safety route (routing report, golden G01) | Router prompt: guidance and two examples for that phrasing. Routing 29/35 to 30/35, safety 5/6 to 6/6. Analyst cases are still the weakest route |
| 19 | The golden hero expectation asked for separate patient-fact and retrieved-source statements, which is stricter than the spec (a renal consideration with patient evidence and source evidence). The validator drops supporting statements that no conclusion cites, by design | Expectation changed to: a hedged conclusion whose statements together cite both patient and source evidence. The change was made after seeing runs fail, and is recorded here for that reason |
| 20 | When Cortex Analyst cannot turn a question into a query, the API answers `503 agent_unavailable`, which the UI shows as "the assistant is unavailable" | Left as is, recorded as a UX finding: the wording blames the service for what is really an unsupported question |
| 21 | A Snowflake `COMPLETE` call occasionally fails (`complete_failed`, Snowflake error 604, a cancelled statement) and hero latency ranges from 14 s to 39 s | Reported in the timing report. Hero p50 is 24 s against a 20 s target; no change made |
| 22 | The live suite leaves rows behind in the shared account: pins from the agent-action test, invited and test users (`db:check` counts 9 users where 3 are demo accounts), answers and audit rows | The pin lifecycle test now looks only at its own answer's pins. Cleanup is not automated; reset the demo account before a recorded run |
| 23 | `db.py status` failed (`rows` is a reserved word) | Alias renamed; the command now also prints the resource monitor's credit use |
| 24 | The design direction was built from the plan's proposed palette on the instruction "go ahead and build it", without a separate approval step (ADR-018) | Colours are role tokens in one CSS file, with a contrast check, so a different approved look is a one-file change. `docs/design/design-direction.md` says so |

