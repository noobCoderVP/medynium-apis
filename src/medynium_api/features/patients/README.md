# patients

**Purpose:** List, Patient 360 overview, medications, labs, lab trend, timeline, claims, notes. Denied equals missing. `history_repository.py` holds the timeline, claims and notes SQL.
**Endpoints:** GET /patients, /patients/{id}, /medications, /labs, /labs/{code}/trend, /timeline, /claims, /notes, /notes/{note_id}
**Doctor names:** every medicine, result, diagnosis, timeline event, claim and note carries `doctor {name, speciality, basis}` (`attach.py`, resolved by `core/intel/doctors.py`): who typed it in the app, who wrote the note, or the visit's or claim's clinician. When the data names nobody the patient's treating doctor is returned with basis `treating`, which the screens show in a lighter style as "Treating: ...". The overview also returns `treating_doctors`.
**Requirements:** FR-01 to FR-04, SEC-05; B-5
**May import:** `core/` only, never another feature. SQL lives in `repository.py` files (`core/` holds shared SQL helpers).
**Status:** built; 13 live tests
