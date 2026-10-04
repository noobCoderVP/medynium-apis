# knowledge

**Purpose:** Label search with full citations, brand resolution, drug browsing and snapshot status.
**Endpoints:** GET /knowledge/search (text, drug, or both), GET /knowledge/drugs, GET /knowledge/status
**Requirements:** FR-06, SEC-04; K-6, K-7
**May import:** `core/` only, never another feature. SQL lives in `repository.py` files (`core/` holds shared SQL helpers).
**Status:** built; 13 live tests plus unit tests for name matching; retrieval eval at 1.0 (negatives included)

**How a search resolves**
- `names.py` (pure, no I/O) matches drug names, Indian brands, prefixes (5+ letters) and near-miss spellings (6+ letters) against the alias map, and section headings in any case ("warnings" also finds "Boxed warning").
- An explicit `drug` filter wins over names found in `q`. A drug with no `q` browses its sections from `DOCUMENT_CHUNK` (safety sections first, no model, no search call).
- Unfiltered text needs a score of 0.34, or 0.50 without a word check: every content word must appear in the returned text, otherwise the question is about something the index does not hold and the answer is a gap (this keeps `ivermectin dosing` empty while `renal` and `pregnancy` find sections).
- A gap carries a message and, for an unknown drug, the nearest indexed drugs in `suggestions`.
- Drug aliases, drug directory and section names are cached for 5 minutes per role; the corpus is a controlled snapshot.
