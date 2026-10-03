# Authentication, accounts and administration

Conventions, errors and cookies: [README.md](README.md). Design: [../architecture/security-and-access.md](../architecture/security-and-access.md). Tables: [../database/security.md](../database/security.md).

## Sign in

### `POST /auth/login` (Public)

Request:

```json
{ "email": "sharma@demo.medynium", "password": "••••••••••••" }
```

Response `200`, with `Set-Cookie: med_access=...; med_refresh=...`:

```json
{
  "user": {
    "user_id": "7f0c2f2e-5b43-4a43-9a4e-2f4d0d8c1a11",
    "email": "sharma@demo.medynium",
    "display_name": "Dr. Sharma",
    "role": "DOCTOR",
    "is_admin": true
  },
  "session_expires_at": "2026-10-10T08:00:00Z"
}
```

Errors: `401 unauthorized` (wrong email or password, or account disabled or locked: **same message**), `429 rate_limited`, `400 invalid_request`. Five failures lock the account for 15 minutes. Every attempt writes `SECURITY.AUTH_EVENT`.

### `POST /auth/refresh` (refresh cookie)

No body. Rotates both cookies and returns `204`. `401 unauthorized` if the refresh token is expired, revoked, or **reused** (reuse revokes the whole session).

### `POST /auth/logout`

Revokes the session and clears cookies. `204`.

### `GET /me`

```json
{
  "user_id": "7f0c2f2e-...",
  "email": "sharma@demo.medynium",
  "display_name": "Dr. Sharma",
  "role": "DOCTOR",
  "is_admin": true,
  "supervising_doctor_id": null,
  "patient_count": 148,
  "permissions": ["patients:read", "copilot:ask", "agent:actions", "admin:users"]
}
```

`permissions` is informational for the UI; the server enforces access itself.

### `POST /auth/password`

```json
{ "current_password": "...", "new_password": "..." }
```

`204`. Bumps the token version and revokes other sessions. `400 invalid_request` if the new password breaks the rules; `401` if the current password is wrong.

## Invitations

### `GET /auth/invites/{token}` (Public)

Lets the accept page show who is being invited.

```json
{ "email": "new.doctor@clinic.example", "display_name": "Dr. Rao", "role": "DOCTOR", "expires_at": "2026-10-06T08:00:00Z" }
```

`404 not_found` for an unknown, expired, revoked or used token (indistinguishable).

### `POST /auth/invites/accept` (Public)

```json
{ "token": "<one-time token>", "password": "...", "display_name": "Dr. Rao" }
```

Creates the user, provisions the Snowflake role and entitlements, marks the invite accepted. `201`:

```json
{ "email": "new.doctor@clinic.example" }
```

The user then signs in normally. Errors: `404 not_found` (bad token), `400 invalid_request` (password rules).

## Admin: users (admin doctors only)

All endpoints below need `is_admin`; otherwise `403 forbidden`.

### `POST /admin/invites`

```json
{
  "email": "assistant@demo.medynium",
  "display_name": "Meera Joshi",
  "role": "ASSISTANT",
  "is_admin": false,
  "supervising_doctor_id": "7f0c2f2e-...",
  "patient_ids": ["P-1042", "P-1067"]
}
```

`201`:

```json
{
  "invite_id": "b3c1...",
  "email": "assistant@demo.medynium",
  "accept_url": "https://medynium.example/accept?token=...",
  "expires_at": "2026-10-06T08:00:00Z"
}
```

The link is shown **once**; only its hash is stored. No email is sent (ADR-005). Rules: an `ASSISTANT` requires `supervising_doctor_id`; `patient_ids` for an assistant must be a subset of that doctor's patients; `409 conflict` if the email already has an active account or pending invite.

### `GET /admin/invites`, `DELETE /admin/invites/{invite_id}`

List invites (`status`, `email`, `role`, `expires_at`; no token) and revoke a pending one (`204`).

### `GET /admin/users`

Query: `q` (name or email), `role`, `status`, `limit`, `offset`. Returns the standard list shape with items like:

```json
{
  "user_id": "...", "email": "...", "display_name": "Meera Joshi",
  "role": "ASSISTANT", "is_admin": false, "status": "ACTIVE",
  "supervising_doctor_id": "...", "patient_count": 31, "last_login_at": "2026-10-03T06:11:00Z"
}
```

### `GET /admin/users/{user_id}`, `PATCH /admin/users/{user_id}`

`PATCH` body (any subset): `{ "display_name": "...", "is_admin": true, "status": "DISABLED" }`. Disabling bumps the token version, revokes sessions and writes `AUTH_EVENT`. An admin cannot disable or demote themselves if they are the last admin (`409 conflict`).

### `POST /admin/users/{user_id}/reset-password`

Returns a one-time reset link in the same shape as an invite (`accept_url`, `expires_at`), usable once with `POST /auth/invites/accept`-style handling. Revokes the user's sessions.

### `GET /admin/users/{user_id}/entitlements`

```json
{ "user_id": "...", "patient_ids": ["P-1042", "P-1067"], "total": 2 }
```

### `PUT /admin/users/{user_id}/entitlements`

Replaces the user's active set.

```json
{ "patient_ids": ["P-1042", "P-1067", "P-1101"] }
```

`200` with the same shape as `GET`. Server rules (via `SET_ENTITLEMENTS`): the caller must themselves be entitled to every patient they grant, unless they are an admin granting to a doctor; an assistant's set must be a subset of the supervising doctor's; patients that do not exist are rejected with `400 invalid_request` and a `details` list (admins may see that a patient id is unknown; this does not apply to non-admin endpoints). Writes `AUTH_EVENT`.

## Permission matrix

| Endpoint group | Doctor | Doctor + admin | Assistant |
| --- | --- | --- | --- |
| Own session, `me`, password | yes | yes | yes |
| Patient data, Copilot, evidence, own audit | entitled patients | entitled patients | entitled patients |
| Knowledge search | yes | yes | yes |
| Golden run, skills, health details | yes (golden, skills) | yes | no |
| User, invite, entitlement admin | no | yes | no |
