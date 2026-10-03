# Security and access model

Status: **Draft for review.** Implements SEC-01 to SEC-12 and FR-01, FR-09 with real accounts and admin-invite onboarding.

## 1. Principles

1. The AI is never an authorization loophole.
2. Authorization lives in Snowflake (row access policies) **and** in the API (second layer). Neither trusts the other.
3. Denied equals non-existent: same status, same body, similar latency (SEC-05).
4. No runtime path uses an administrator role (SEC-06). No secret is committed (SEC-07).

## 2. Identities

| Identity | Kind | Used by | Privileges |
| --- | --- | --- | --- |
| **App user** | Row in `SECURITY.APP_USER` | A person signing in | None directly in Snowflake. Each has a Snowflake role `U_<user_id>`. |
| **`MED_API`** | Snowflake service user, key-pair auth | The deployed API | Can `USE ROLE` any `U_*` role; can `SELECT` on `SECURITY.APP_USER`, `AUTH_SESSION` and call provisioning procedures. **No direct privilege on `CLINICAL` or `ANALYTICS` patient tables.** |
| **`U_<user_id>`** | Snowflake role, one per app user | A request, after `USE ROLE` | Inherits `MED_DOCTOR` or `MED_ASSISTANT`. Sees only entitled patients through the row access policy. |
| **`MED_DOCTOR`, `MED_ASSISTANT`** | Base roles | Inherited by `U_*` | Read on the analytics and clinical objects, read on `KNOWLEDGE`, insert on audit and answer tables. No write to `CLINICAL`. |
| **`MED_AGENT_READ`** | Role | CoCo skills and the golden-run job | Read-only, scoped. |
| **`MED_ADMIN`** | Role | A person running setup scripts | Creates objects and loads data. Never used by the deployed API. |

There is no shared account that can see every patient serving requests (SEC-03). A leaked `MED_API` key can impersonate users but cannot read patient rows without assuming a `U_*` role, which the audit trail attributes to a user.

## 3. Sign-in, sessions and tokens

| Item | Design |
| --- | --- |
| Credential | Email and password. Password hashed with **argon2id** in the API; only the hash is stored. |
| Password rules | At least 12 characters, not in a common-password list, not equal to the email. |
| Lockout | 5 failed attempts lock the account for 15 minutes; also rate-limited by IP. The error is the same `unauthorized` whether the email exists or not. |
| Access token | Signed JWT (HS256, `SESSION_SECRET`), 15-minute lifetime, claims `sub` (user id), `role`, `adm`, `ver` (token version), `sid` (session id). Cookie `med_access`, `HttpOnly; Secure; SameSite=Lax; Path=/`. |
| Refresh token | Random 256-bit value, 7-day lifetime, rotated on every use. Cookie `med_refresh`, `HttpOnly; Secure; SameSite=Lax; Path=/auth`. Only its SHA-256 hash is stored in `SECURITY.AUTH_SESSION`. Reuse of an old refresh token revokes the whole session. |
| Verification | Access tokens are verified without a database call. Refresh, login and invites hit Snowflake. |
| Revocation | Disabling a user or changing a password bumps `TOKEN_VERSION` and revokes sessions. Refresh fails at once; an already-issued access token stays valid for up to 15 minutes. A short in-process cache of `TOKEN_VERSION` per user (30 s) can close that gap if needed. |
| CSRF | `SameSite=Lax` plus a required `X-Medynium-Client: web` header on every non-GET request. |
| MFA | Not in scope for the hackathon build. Documented as the first hardening step. |

Why not a managed identity provider: you chose Snowflake-backed accounts (see ADR-002). The cost is that we own the password and session code, so it is deliberately small and listed in the test plan.

## 4. Onboarding: admin invites only

1. An admin (a doctor with `IS_ADMIN`) calls `POST /admin/invites` with email, role and optional patient list.
2. The API stores a `USER_INVITE` row with the SHA-256 of a one-time token (valid 72 hours) and returns an accept link. No email system is required; the admin shares the link. Email delivery is an optional later add-on.
3. The invitee opens the link, sets a password, and the API calls `SECURITY.PROVISION_USER` (see below), creating the user row, the Snowflake role `U_<user_id>` and its grants.
4. The invitee signs in normally.

An assistant is always linked to a **supervising doctor** (`SUPERVISING_DOCTOR_ID`). An assistant can only be entitled to patients that the supervising doctor is entitled to (FR-01).

## 5. Patient access in Snowflake

### 5.1 Entitlement table

`SECURITY.PATIENT_ENTITLEMENT` holds one active row per (patient, user), including the user's Snowflake role name. See [../database/security.md](../database/security.md).

### 5.2 Row access policy (sketch, validated in Slice 2)

```sql
CREATE OR REPLACE ROW ACCESS POLICY SECURITY.PATIENT_RAP AS (patient_id STRING)
RETURNS BOOLEAN ->
  IS_ROLE_IN_SESSION('MED_ADMIN')   -- setup and tests only; not granted to MED_API or U_* roles
  OR EXISTS (
    SELECT 1
    FROM SECURITY.PATIENT_ENTITLEMENT e
    WHERE e.PATIENT_ID = patient_id
      AND e.REVOKED_AT IS NULL
      AND IS_ROLE_IN_SESSION(e.SNOWFLAKE_ROLE)
  );
```

Attached with `ALTER TABLE ... ADD ROW ACCESS POLICY SECURITY.PATIENT_RAP ON (PATIENT_ID)` to **every** table and view that carries `PATIENT_ID`, including precomputed `ANALYTICS` tables, `ANSWER`, `ANSWER_EVIDENCE`, `COPILOT_AUDIT` and `PIN`. A table checklist and an automated test enforce "no `PATIENT_ID` table without the policy".

### 5.3 Per-request role

The API keeps a small pool of `MED_API` connections. For each request that needs patient data it leases a connection and runs:

```sql
USE SECONDARY ROLES NONE;
USE ROLE U_<user_id>;
```

and resets the role when the connection is returned. Role names are built only from a validated UUID, never from user input.

### 5.4 Provisioning procedures

`MED_API` cannot create roles or grant privileges directly. It calls owner's-rights stored procedures owned by a dedicated role that holds the needed privileges:

| Procedure | Does | Guard |
| --- | --- | --- |
| `SECURITY.PROVISION_USER(user_id, base_role)` | Creates `U_<id>`, grants it to `MED_API` and to the base role's children | Called only after a valid invite is consumed |
| `SECURITY.DEPROVISION_USER(user_id)` | Revokes and drops the role; revokes entitlements | Admin only |
| `SECURITY.SET_ENTITLEMENTS(user_id, patient_ids, granted_by)` | Replaces a user's patient set | Checks the grantor's own entitlements, and for assistants the supervising doctor's |

### 5.5 API-side second layer

Before any query the API resolves the caller from the token and applies an entitlement check by calling the same patient lookup under the user's role. If the policy returns no row, the response is the standard `not_found`. The API never returns "forbidden" for a patient resource.

## 6. AI layer and access

| Surface | How access binds |
| --- | --- |
| Plain SQL routes | Run under `U_<id>`; the policy filters rows. |
| Cortex Analyst | Called with the semantic view under the user's role, so generated SQL is filtered by the policy. |
| Cortex Search | Indexes `KNOWLEDGE.DOCUMENT_CHUNK` only, which contains **no patient data** (SEC-04). |
| Cortex Agent | Runs under the user's role with the Analyst and Search tools. |
| Router model | Never receives patient records or document text. |

If the validation spike shows the AI layer does not honour the role, the fallback is: the API runs the permitted SQL itself under the user's role and sends only those rows to the model, and Search stays public-docs-only. G4 is then tested through all three layers.

## 7. Validation spike (Slice 2) {#validation-spike}

Before building on this design, prove in a scratch schema:

1. A row access policy that uses `IS_ROLE_IN_SESSION(<column>)` inside an `EXISTS` over the entitlement table filters correctly, on tables **and** on precomputed tables.
2. `MED_API` can `USE ROLE U_x` and read only entitled rows, and a role it was not granted fails.
3. Cortex Analyst, called with the user's role, cannot return a non-entitled patient.
4. Cortex Agent REST accepts the per-user role.
5. Policy evaluation cost on a few hundred patients is negligible.

Outcome is recorded in [decisions.md](decisions.md) (ADR-003). If check 1 or 2 fails, the alternative is a Snowflake **user** per app user (key pair provisioned at invite time, private key encrypted at rest), which costs more secret handling but changes nothing else here.

## 8. Audit

| Table | Records |
| --- | --- |
| `SECURITY.AUTH_EVENT` | Logins (success and failure), logouts, refresh reuse, lockouts, invites, role changes, entitlement changes, password changes. |
| `ANALYTICS.COPILOT_AUDIT` | Every Copilot question and agent action: user, role, route, model, confidence, action, patient, question, answer id, evidence ids, steps, outcome, time. **Denied attempts are included.** |

Runtime roles can insert but not update or delete either table. The caller sees only their own `COPILOT_AUDIT` rows; admins see `AUTH_EVENT`.

## 9. Secrets

| Secret | Where | Rotation |
| --- | --- | --- |
| `MED_API` private key | Render secret (`SNOWFLAKE_API_PRIVATE_KEY_B64`) | Replace the key pair, update the secret, redeploy |
| `SESSION_SECRET` | Render secret (generated) | Rotating signs everyone out |
| Admin setup key or token | Your machine only, never deployed | Revoke after bootstrap |
| User passwords | Never stored; argon2id hash only | User or admin reset |

## 10. Threats considered

| Threat | Mitigation |
| --- | --- |
| Brute-force or credential stuffing | Lockout, IP rate limit, generic errors |
| Patient enumeration | Same 404 body and similar latency for denied and missing; no patient ID in error text |
| Prompt injection in notes or labels | Source text treated as data, validator drops unbacked statements, router never sees data (S5 test) |
| Router steered into an action | Server allowlist; low confidence escalates to `safety` or asks, never to `action` |
| Cross-patient question | Refused by router rules and by a server rule; validator rejects SQL touching another patient |
| Stolen cookie | `HttpOnly`, short access lifetime, rotating refresh with reuse detection |
| Insider with `MED_API` key | Cannot read rows without a role; role use is attributable; rotate the key |
| Secrets in git | `.env` ignored, pre-commit secret scan, `.env.example` only |
