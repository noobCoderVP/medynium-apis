# auth

**Purpose:** Sign-in, refresh rotation with reuse detection, lockout, sign-out, current user, password change, invitation preview and acceptance (also completes a password reset).
**Endpoints:** POST /auth/login, /auth/refresh, /auth/logout, /auth/password, /auth/invites/accept; GET /me, /auth/invites/{token}
**Requirements:** SEC-01, SEC-03, SEC-05, FR-01; B-2
**May import:** `core/` only, never another feature. SQL lives in `repository.py` files (`core/` holds shared SQL helpers).
**Status:** built; 6 live tests

**Email and codes:** `POST /auth/password/forgot` (public, always 204) mails a one-time reset link; with `LOGIN_OTP_ENABLED` `POST /auth/login` returns an `OtpChallenge` and `POST /auth/login/verify` finishes with the emailed six-digit code. Mail goes through `core/email` (Resend); with no `RESEND_API_KEY` nothing is sent. Invitation and reset logic lives in `invites.py`.
