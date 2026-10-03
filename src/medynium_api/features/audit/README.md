# audit

**Purpose:** The caller's own audit entries, denials included.
**Endpoints:** GET /audit
**Requirements:** FR-10, SEC-09; B-6
**May import:** `core/` only, never another feature. SQL lives in `repository.py` files (`core/` holds shared SQL helpers).
**Status:** built; live tests
