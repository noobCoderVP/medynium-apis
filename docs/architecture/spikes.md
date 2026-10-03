# Spike results (Stage 0)

Run on 2026-10-03 against account `PSYMVEK-AI12714` (Azure Central India). Scripts are in `scripts/spikes/`; scratch objects were dropped afterwards. Each spike ends in a decision.

## S-A. Per-user role honoured by row access policies and Cortex: **PASS, keep ADR-003**

`scripts/spikes/s_a_role_access.py`, `s_b_cortex_rest.py`, `s_b_agent.py`.

| Step | Result |
| --- | --- |
| Service user `MED_API_SVC` with role `MED_API` alone cannot read the patient table | Pass |
| `USE ROLE U_A`: sees only A's patients through a row access policy using `IS_ROLE_IN_SESSION(<column>)` inside `EXISTS` over the entitlement table | Pass |
| Switch to `U_B` on the same connection: result flips; switching back leaks nothing | Pass |
| A role **not granted** to the service user is refused | Pass |
| Two concurrent connections with different roles, 200 queries: no cross-talk | Pass |
| Cortex Analyst REST with `X-Snowflake-Role: U_A`: returns SQL over the semantic view; executing it under `U_A` returns only A's rows, `U_B` only B's | Pass |
| Cortex Agent REST `:run` with `X-Snowflake-Role`: user A's run saw 2 patients, user B's saw 1 | Pass |

Design consequences:

1. **Grant per-user roles to the service USER, not to the `MED_API` role.** `GRANT ROLE U_x TO USER MED_API_SVC`. Granting `U_x` to the role `MED_API` would make `MED_API` inherit every user's access. Set `DEFAULT_SECONDARY_ROLES = ()` on the service user and run `USE SECONDARY ROLES NONE` on every leased connection.
2. Semantic views inherit the row access policy of their source tables.
3. Cortex Analyst only **returns SQL**; the API runs it under the user's role, so access holds by construction.
4. The REST calls authenticate with a key-pair JWT: `iss = ACCOUNT.USER.SHA256:<fingerprint>`, `sub = ACCOUNT.USER`, header `X-Snowflake-Authorization-Token-Type: KEYPAIR_JWT`, and the role in `X-Snowflake-Role`.

## S-B. Cortex Agent and Analyst call shape: **recorded**

| Item | Finding |
| --- | --- |
| Analyst | `POST https://<account>.snowflakecomputing.com/api/v2/cortex/analyst/message` with `{"messages":[...], "semantic_view":"DB.SCHEMA.VIEW"}`. About 5 to 6 s. Response `message.content[]` has items of `type` `text` and `sql` (`statement`). |
| Semantic view DDL | `CREATE SEMANTIC VIEW ... TABLES (...) DIMENSIONS (...) METRICS (...)` works. Query form `SELECT * FROM SEMANTIC_VIEW(view FACTS ... )`. |
| Agent object | `CREATE AGENT db.schema.name FROM SPECIFICATION $$ yaml $$` with `models.orchestration`, `instructions`, `tools` and `tool_resources`. Needs `GRANT USAGE ON AGENT` to the caller's base role. |
| Agent run | `POST /api/v2/databases/{db}/schemas/{schema}/agents/{name}:run`, `Accept: text/event-stream`. |
| Stream events | `response.status`, `response.thinking(.delta)`, `response.tool_use`, `response.tool_result.status`, `response.tool_result`, `response.text(.delta)`, `response.table`, `response.suggested_queries`, `response`, then `[DONE]`. |
| Evidence in the stream | `response.tool_result.content[].json` carries `sql`, `query_id` and `result_set.data` for the executed query: enough to capture SQL and rows for the Why? panel. |
| Latency | **About 15 to 16 s for a trivial two-row question.** A real safety run with Search would exceed the 20 s target. |

## S-D. Models: **PASS, with an output-length rule**

Warm, `SNOWFLAKE.CORTEX.COMPLETE`:

| Model | First call | Short p50 | 1,000-token answer |
| --- | --- | --- | --- |
| `llama3.1-8b` (router) | 0.6 s | 0.7 s | 6.7 s |
| `claude-haiku-4-5` | 1.4 s | 1.3 s | 9.1 s |
| `claude-sonnet-4-6` (strong) | 1.5 s | 2.0 s | 17.6 s |

The router is well inside the 2 s target. Sonnet's time is dominated by output length, so the safety answer must stay compact (target 300 to 500 tokens, hard cap 700). Cross-region inference was not needed: all three models answered on this account.

## S-C. SSE end to end: **deferred**

Needs the UI proxy and the Cloud Run deployment. Tested locally through the Next.js `/api` proxy in Stage 6 and on Cloud Run at G-2. The API streams with `sse-starlette` and sends a keepalive every 15 s.

## Decisions taken from the spikes

| ADR | Decision |
| --- | --- |
| ADR-003 | **Accepted.** One service user, one role per app user, granted to the user. |
| ADR-015 | **Safety route default is the evidence-pack path**: deterministic SQL under the user's role, Cortex Search, then a single `COMPLETE` call with the strong model and a compact structured output. This is controllable and fits the time budget. The Cortex Agent path is built behind a setting (`SAFETY_PATH=pack\|agent`) so the Analyst, Search and Agent story remains available, but it is not the default because of its latency. |
| Output budget | Safety answers are limited to about 500 tokens; the validator, not the model, decides what is shown. |
