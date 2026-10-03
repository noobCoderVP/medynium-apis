# pins

**Purpose:** Evidence pinned to a patient workspace. Same service behind the Pin icon and the pin_evidence action.
**Endpoints:** GET/POST /patients/{id}/pins, DELETE /patients/{id}/pins/{pin_id}
**Requirements:** FR-19, FR-20; B-6
**May import:** `core/` only, never another feature. SQL lives in `repository.py` files (`core/` holds shared SQL helpers).
**Status:** built; live tests
