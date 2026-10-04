# similar

**Purpose:** For the open patient, the closest of the clinician's OWN patients, ranked and explained: shared diagnoses, shared medicines, abnormal results in the same direction, with a side-by-side comparison on the screen. A comparison aid; it never predicts an outcome or recommends anything, and says so on every result.
**Endpoints:** GET /patients/{id}/similar
**Requirements:** production plan Phase 5 (P5.0 to P5.7); SEC-02, SEC-05; AI-10 (the assistant's `similar_patients` tool uses the same search)
**How it works:** `core/similar.py` (shared with the assistant) blends embedding similarity with structured overlap. Vectors live in `ANALYTICS.PATIENT_EMBEDDING` under the entitled-patient policy, so a user can only be shown patients they already have. The text embedded comes from the `PATIENT_CASE_SUMMARY` view: age band, sex, diagnoses, medicines and abnormal results, never a name, city, id or note text. A changed patient is re-embedded by the background refresh, and only when the summary changed.
**Rules:** a denied patient is audited and answered like a missing one. Every search is audited (`SIMILAR_PATIENTS`). The list is never padded: below a minimum score a patient is not shown, and the response says how many there are. A de-identified cohort across other clinicians is NOT built; it needs its own access model and sign-off (see the plan).
**May import:** `core/` only, never another feature.
**Status:** built; unit tests in `tests/test_similar.py`, live tests in `tests/integration/test_similar.py`.
