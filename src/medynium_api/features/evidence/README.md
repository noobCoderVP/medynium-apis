# evidence

**Purpose:** The Why? data for one answer: records, SQL, sources, statement map. Own answers only.
**Endpoints:** GET /evidence/{answer_id}
**Requirements:** FR-08, NFR-05; A-7
**May import:** `core/` only, never another feature. SQL lives in `repository.py` files (`core/` holds shared SQL helpers).
**Status:** built; covered by the copilot tests
