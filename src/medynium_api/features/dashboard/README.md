# dashboard

**Purpose:** Worklist with change flags, recent lab and medication changes, utilisation. No AI call.
**Endpoints:** GET /dashboard, GET /dashboard/briefing
**Requirements:** FR-17; B-4
**May import:** `core/` only, never another feature. SQL lives in `repository.py` files (`core/` holds shared SQL helpers).
**Status:** dashboard built (4 live tests); briefing is a 501 stub (A-13)
