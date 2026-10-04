# brief

**Purpose:** The first screen of a patient: what to look at, what changed, what is missing, as fixed rules over the read models, each item naming the record it came from. The rules live in `core/intel/` (shared with the assistant's `get_attention`, `detect_changes` and `get_gaps` tools, so a person and the assistant see the same items). No model call, except the optional written summary.
**Endpoints:** GET /patients/{id}/brief, /brief/summary, /attention, /changes?from=previous_visit|90d|1y|YYYY-MM-DD, /gaps
**Requirements:** FR-03, FR-05, FR-17, SEC-05, AI-03, AI-04; agentic upgrade phase D
**Stored written summary:** `GET /patients/{id}/summary` returns the markdown summary stored in `ANALYTICS.PATIENT_SUMMARY` with when it was written and by whom (`changed_since` is true when the app recorded a change afterwards); `POST /patients/{id}/summary/refresh` writes it again (about fifteen seconds) from the facts in `core/intel/profile.py`. The model may only restate those facts (numbers checked, advice and reassurance rejected); on failure a rule-made summary of the same facts is stored and labelled `rules`.
**Rules:** a denied patient is audited and answered like a missing one. Every read runs under the caller's role. Gap rules are usual follow-up checks (for example HbA1c for a patient on metformin), worded as "not seen in the last N months", never as a statement that the patient is fine. The written summary may only rephrase the rule signals: every number in it must already be in them, and advice or reassurance is rejected, in which case the rule-made headline is shown instead.
**May import:** `core/` only, never another feature.
**Status:** built; rule tests in `tests/test_intel_rules.py`, live tests in `tests/integration/test_brief.py`.
