# copilot

**Purpose:** Routing, the safety review, route handlers (lookup, changed, analyst, knowledge, refuse), the action allowlist and SSE. Modules: routing, handlers/, actions, safety, pack, service, repository, ports.
**Endpoints:** POST /copilot/ask, POST /patients/{id}/safety-review, POST /agent/actions
**Requirements:** FR-05, FR-07, FR-18 to FR-21, AI-01 to AI-12, SEC-11, SEC-12; A-1 to A-12
**May import:** `core/` only, never another feature. SQL lives in `repository.py` files (`core/` holds shared SQL helpers).
**Status:** built; OPEN BUG: saving evidence fails for answers with no sources (lookup, changed, analyst); routing set and Cortex Agent path not built
