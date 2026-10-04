# copilot

**Purpose:** Routing, the safety review, route handlers (lookup, changed, analyst, knowledge, panel, refuse), the action allowlist and SSE. Modules: routing, handlers/, panel*, actions, safety, pack, service, repository, ports.
**Endpoints:** POST /copilot/ask, POST /patients/{id}/safety-review, POST /agent/actions
**Requirements:** FR-05, FR-07, FR-18 to FR-21, AI-01 to AI-12, SEC-11, SEC-12; A-1 to A-12
**May import:** `core/` only, never another feature. SQL lives in `repository.py` files (`core/` holds shared SQL helpers).
**Panel route:** questions about the clinician's own patients ("who are my patients and what is pending", "which of my patients have low eGFR", "patients like this one"). `panel_plan.py` plans with rules first and the router model second; the plan is validated (closed tool names, whitelisted filters). Five read-only tools: list_my_patients, pending_work, changes_since, patients_matching, similar_patients. Statements carry `patient_id` and `group`. Other doctors' patients and the whole database are still refused.
**Actions:** an agent-planned action stays on the open patient (`actions.py`); the action set is still closed.
**Status:** built. Evaluated by `scripts/eval_golden.py` (golden 19, injection 12) and `scripts/eval_routing.py` (47 cases); results in `docs/quality/` and `docs/evals/`.
