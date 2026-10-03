# auth

**Purpose:** Sign-in, refresh rotation with reuse detection, lockout, sign-out, current user, password change, invitation preview and acceptance (also completes a password reset).
**Endpoints:** POST /auth/login, /auth/refresh, /auth/logout, /auth/password, /auth/invites/accept; GET /me, /auth/invites/{token}
**Requirements:** SEC-01, SEC-03, SEC-05, FR-01; B-2
**May import:** `core/` only, never another feature. SQL lives in `repository.py` files (`core/` holds shared SQL helpers).
**Status:** built; 6 live tests
