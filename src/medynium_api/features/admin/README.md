# admin

**Purpose:** Invitations, user list and edit, disable and re-enable, reset links, entitlement sets. Doctors with IS_ADMIN only.
**Endpoints:** POST/GET /admin/invites, DELETE /admin/invites/{id}, GET /admin/users, GET/PATCH /admin/users/{id}, POST /admin/users/{id}/reset-password, GET/PUT /admin/users/{id}/entitlements
**Requirements:** FR-01, SEC-06; B-3
**May import:** `core/` only, never another feature. SQL lives in `repository.py` files (`core/` holds shared SQL helpers).
**Status:** built; 6 live tests. Golden-run and skills endpoints are not built
