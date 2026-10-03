# SECURITY schema

Accounts, sessions, entitlements and their audit. No patient data. Only `MED_API` (through the procedures below) and `MED_ADMIN` touch these tables; app-user roles `U_*` have read access to `PATIENT_ENTITLEMENT` only through the row access policy's own evaluation.

## APP_USER

One row per person who can sign in.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `USER_ID` | VARCHAR | no | PK. UUID. Used to build the role name `U_<USER_ID with dashes removed>`. |
| `EMAIL` | VARCHAR | no | Unique, stored lower-case. |
| `DISPLAY_NAME` | VARCHAR | no | e.g. "Dr. Sharma". |
| `ROLE_CODE` | VARCHAR | no | `DOCTOR` or `ASSISTANT`. |
| `IS_ADMIN` | BOOLEAN | no | Only meaningful for doctors. Allows user and entitlement management. |
| `SUPERVISING_DOCTOR_ID` | VARCHAR | yes | Required for `ASSISTANT`; FK to `APP_USER.USER_ID` where role is `DOCTOR`. |
| `STATUS` | VARCHAR | no | `ACTIVE`, `DISABLED`. (Pending invitations live in `USER_INVITE`.) |
| `PASSWORD_HASH` | VARCHAR | no | argon2id encoded string. Never logged or returned. |
| `PASSWORD_UPDATED_AT` | TIMESTAMP_NTZ | no | |
| `FAILED_LOGINS` | NUMBER | no | Reset on success. |
| `LOCKED_UNTIL` | TIMESTAMP_NTZ | yes | Set after 5 failures for 15 minutes. |
| `TOKEN_VERSION` | NUMBER | no | Bumped on disable, password change, forced logout. Carried in the access token. |
| `SNOWFLAKE_ROLE` | VARCHAR | no | `U_<id>`. Created by `PROVISION_USER`. |
| `CREATED_AT`, `CREATED_BY` | TIMESTAMP_NTZ, VARCHAR | no | `CREATED_BY` is the inviting admin's `USER_ID`. |
| `LAST_LOGIN_AT` | TIMESTAMP_NTZ | yes | |

Constraints: unique `EMAIL`; assistant must have a supervising doctor; a supervising doctor must be a `DOCTOR`.

## USER_INVITE

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `INVITE_ID` | VARCHAR | no | PK. UUID. |
| `EMAIL` | VARCHAR | no | Lower-case. |
| `DISPLAY_NAME` | VARCHAR | no | |
| `ROLE_CODE` | VARCHAR | no | `DOCTOR` or `ASSISTANT`. |
| `IS_ADMIN` | BOOLEAN | no | |
| `SUPERVISING_DOCTOR_ID` | VARCHAR | yes | |
| `PATIENT_IDS` | VARIANT | yes | Patients to entitle on acceptance. |
| `TOKEN_HASH` | VARCHAR | no | SHA-256 of the one-time token. The token itself is never stored. |
| `STATUS` | VARCHAR | no | `PENDING`, `ACCEPTED`, `REVOKED`, `EXPIRED`. |
| `EXPIRES_AT` | TIMESTAMP_NTZ | no | 72 hours after creation. |
| `INVITED_BY`, `CREATED_AT`, `ACCEPTED_AT` | | | |

## AUTH_SESSION

One row per refresh-token lineage (one sign-in on one device).

| Column | Type | Notes |
| --- | --- | --- |
| `SESSION_ID` | VARCHAR | PK, UUID. Carried as `sid` in the access token. |
| `USER_ID` | VARCHAR | FK. |
| `REFRESH_HASH` | VARCHAR | SHA-256 of the current refresh token. |
| `PREVIOUS_HASH` | VARCHAR | Hash of the previous token, kept to detect reuse. |
| `CREATED_AT`, `LAST_USED_AT`, `EXPIRES_AT` | TIMESTAMP_NTZ | Absolute lifetime 7 days from creation. |
| `REVOKED_AT` | TIMESTAMP_NTZ | Set on logout, reuse detection, disable. |
| `USER_AGENT`, `IP_ADDRESS` | VARCHAR | For the activity trail; not used for authorisation. |

Expired and revoked rows older than 30 days are deleted by a maintenance script.

## PATIENT_ENTITLEMENT

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `ENTITLEMENT_ID` | VARCHAR | no | PK. |
| `PATIENT_ID` | VARCHAR | no | FK to `CLINICAL.PATIENT`. |
| `USER_ID` | VARCHAR | no | FK to `APP_USER`. |
| `SNOWFLAKE_ROLE` | VARCHAR | no | Copied from `APP_USER`; read by the row access policy. |
| `GRANTED_BY` | VARCHAR | no | Admin or doctor `USER_ID`. |
| `GRANTED_AT` | TIMESTAMP_NTZ | no | |
| `REVOKED_AT` | TIMESTAMP_NTZ | yes | A row with a null value is active. |

Rules enforced by `SET_ENTITLEMENTS`: an assistant is entitled only to patients their supervising doctor is entitled to; revoking a doctor's entitlement also revokes their assistants' for that patient. At most one active row per (patient, user).

## AUTH_EVENT

Append-only. Runtime roles insert but never update or delete.

| Column | Type | Notes |
| --- | --- | --- |
| `EVENT_ID` | VARCHAR | PK. |
| `EVENT_AT` | TIMESTAMP_NTZ | UTC. |
| `EVENT_TYPE` | VARCHAR | `LOGIN_SUCCESS`, `LOGIN_FAILURE`, `LOCKOUT`, `LOGOUT`, `REFRESH`, `REFRESH_REUSE`, `PASSWORD_CHANGE`, `INVITE_CREATED`, `INVITE_ACCEPTED`, `USER_DISABLED`, `USER_ENABLED`, `ENTITLEMENT_CHANGE`. |
| `USER_ID` | VARCHAR | Null when the email is unknown. |
| `ACTOR_ID` | VARCHAR | Who did it, when an admin acted. |
| `EMAIL_ATTEMPTED` | VARCHAR | For failures. |
| `IP_ADDRESS`, `USER_AGENT` | VARCHAR | |
| `DETAIL` | VARIANT | Structured extras, never secrets. |

## Row access policy

`SECURITY.PATIENT_RAP`, attached to every table and view with `PATIENT_ID`. Definition and rationale in [../architecture/security-and-access.md](../architecture/security-and-access.md#52-row-access-policy-sketch-validated-in-slice-2).

### Policy coverage test

A script lists every column named `PATIENT_ID` in `CLINICAL` and `ANALYTICS` from `INFORMATION_SCHEMA.COLUMNS` and compares it with `POLICY_REFERENCES`. Any table without the policy fails the build (`tests/access_check`).

## Procedures

| Procedure | Arguments | Behaviour |
| --- | --- | --- |
| `PROVISION_USER` | `user_id`, `base_role` | Creates `U_<id>`; grants it to `MED_API` and inherits `MED_DOCTOR` or `MED_ASSISTANT`. Idempotent. |
| `DEPROVISION_USER` | `user_id` | Revokes all entitlements and drops the role. |
| `SET_ENTITLEMENTS` | `user_id`, `patient_ids`, `granted_by` | Replaces the user's active set after the checks above; writes `AUTH_EVENT`. |

Procedures run as owner (a role with just `CREATE ROLE` and `MANAGE GRANTS` on the specific objects). `MED_API` has `USAGE` on them and nothing broader.

## Seed accounts (demo)

Created through the same invite path by the seed script, not by direct inserts, so the demo exercises the real flow.

| Email (placeholder) | Role | Admin | Supervising doctor |
| --- | --- | --- | --- |
| `sharma@demo.medynium` | DOCTOR | yes | , |
| `second.doctor@demo.medynium` | DOCTOR | no | , |
| `assistant@demo.medynium` | ASSISTANT | no | `sharma@demo.medynium` |

Real passwords are supplied at seed time through an environment variable and are never written to the repository.

## As built

- Three row access policies, because a table can carry only one: `PATIENT_RAP` (patient data), `PATIENT_OWN_RAP` (answers, evidence, pins and saved views: own rows and still entitled to the patient; a row with no patient, such as a knowledge answer, belongs to its owner), `OWN_RAP` (audit: own rows only, because a denied attempt names a patient the caller is not entitled to). `SECURITY.APPLY_POLICIES()` attaches them all.
- Four procedures owned by `MED_PROVISIONER`: `PROVISION_USER`, `DEPROVISION_USER`, `ENABLE_USER`, `SET_ENTITLEMENTS`. Per-user roles are granted to the service **user** `MED_API_SVC`, never to the `MED_API` role.
- Demo accounts: `sharma@demo.medynium` (doctor, admin, 157 patients including S3), `second.doctor@demo.medynium` (150 patients, none of Sharma's), `assistant@demo.medynium` (36 patients, a subset of Sharma's, S3 excluded).
