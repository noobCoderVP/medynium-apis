# patients

**Purpose:** List, Patient 360 overview, medications, labs, lab trend, timeline, claims, notes. Denied equals missing. `history_repository.py` holds the timeline, claims and notes SQL.
**Endpoints:** GET /patients, /patients/{id}, /medications, /labs, /labs/{code}/trend, /timeline, /claims, /notes, /notes/{note_id}
**Requirements:** FR-01 to FR-04, SEC-05; B-5
**May import:** `core/` only, never another feature. SQL lives in `repository.py` files (`core/` holds shared SQL helpers).
**Status:** built; 13 live tests
