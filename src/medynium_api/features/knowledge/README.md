# knowledge

**Purpose:** Label search with full citations, brand resolution and snapshot status.
**Endpoints:** GET /knowledge/search, GET /knowledge/status
**Requirements:** FR-06, SEC-04; K-6, K-7
**May import:** `core/` only, never another feature. SQL lives in `repository.py` files (`core/` holds shared SQL helpers).
**Status:** built; 6 live tests; retrieval eval at 1.0
