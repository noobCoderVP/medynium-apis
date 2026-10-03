# views

**Purpose:** Saved views and visit briefs. Nothing is stored without an approved preview.
**Endpoints:** POST /views/preview, POST /views, GET /views
**Requirements:** FR-22 (P1); B-6
**May import:** `core/` only, never another feature. SQL lives in `repository.py` files (`core/` holds shared SQL helpers).
**Status:** built; live tests
