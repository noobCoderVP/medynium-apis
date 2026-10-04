# drug_coverage

**Purpose:** Which drugs the knowledge base covers and which it does not, and a way to ask for more. A clinician requests a drug that is not indexed; an admin sees the open requests and a coverage report (indexed against known, National List of Essential Medicines share, the unlabelled medicines most in use among the admin's own patients), decides each request, and adds the label with the setup script.
**Endpoints:** POST/GET /knowledge/requests; GET /admin/knowledge/coverage; GET/PATCH /admin/knowledge/requests[/{id}]
**Requirements:** production plan Phase 4 (P4.5, P4.6); NFR-12 (no outside call at run time); SEC-04
**Rules:** a request changes nothing in the corpus. Adding a label is a setup step (`knowledge/ingest/fetch_openfda.py`, then `extend.py`, then `db.py apply 25`, rebuild the search index, `db.py apply 30`), so the corpus is only ever written by a person, and the `KNOWLEDGE` schema never needs a runtime writer. The plan sketched an admin endpoint that fetches at run time; this build keeps that out on purpose. A drug already indexed is a 409 pointing to search. Asking twice is the same request. The coverage note says the corpus is US labelling.
**May import:** `core/` only, never another feature.
**Status:** built; live tests in `tests/integration/test_drug_coverage.py`.
