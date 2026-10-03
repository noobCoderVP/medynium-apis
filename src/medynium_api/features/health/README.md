# health

**Purpose:** Public liveness and admin details.
**Endpoints:** GET /health, GET /health/details
**Requirements:** NFR-08; B-7
**May import:** `core/` only, never another feature. SQL lives in `repository.py` files (`core/` holds shared SQL helpers).
**Status:** built; live test
