# Knowledge, audit, saved views, admin and health

Conventions and errors: [README.md](README.md).

## Knowledge

Public documents only; searching never touches patient data (SEC-04). Tables: [../database/knowledge.md](../database/knowledge.md).

### `GET /knowledge/search`

Query: `q` (required), `drug` (generic name, optional), `source` (`openFDA`, `ICMR`, `NLEM`), `limit` (default 10, max 25).

```json
{
  "snapshot_date": "2026-10-02",
  "items": [
    {
      "chunk_id": "CH-0412",
      "document_id": "DOC-MET-001",
      "title": "Metformin hydrochloride tablets: prescribing information",
      "source": "openFDA drug labeling",
      "drug": "metformin",
      "section": "Warnings and precautions",
      "version": "Label version 6",
      "effective_date": "2026-08-12",
      "retrieved_date": "2026-10-02",
      "page": null,
      "snippet": "Assess renal function before initiating ...",
      "score": 0.82
    }
  ]
}
```

Every result carries the full citation (FR-06). `page` is present only where the source has pages. Source text is plain text. Searching for a drug that is not indexed returns `items: []` with `snapshot_date`; the UI says "not found in the indexed sources" and never "no risk".

### `GET /knowledge/status`

```json
{ "snapshot_date": "2026-10-02", "document_count": 24, "chunk_count": 168, "drugs": ["metformin", "lisinopril", "atorvastatin"], "sources": ["openFDA"] }
```

Used by answer limits ("24 drugs and 168 chunks indexed") and the admin page.

## Audit

### `GET /audit`

The caller's own entries (FR-10). Query: `patient_id`, `from`, `to`, `action`, `outcome`, `limit`, `offset`. Newest first.

```json
{
  "items": [
    {
      "audit_id": "AUD-000413",
      "occurred_at": "2026-10-03T08:42:14Z",
      "via": "AGENT",
      "action": "RUN_SAFETY_REVIEW",
      "route": "safety", "model": "claude-sonnet-4-6", "confidence": 0.88,
      "cost_note": "strong model",
      "patient_id": "P-1042",
      "question": "Open the kidney-disease patient and run the safety review",
      "answer_id": "ANS-0007",
      "patient_evidence_ids": ["P1", "P2"],
      "document_ids": ["DOC-MET-001"],
      "steps": [ { "step_id": "s1", "label": "Reading medications, labs and diagnoses", "status": "done" } ],
      "outcome": "OK"
    }
  ],
  "total": 14, "limit": 50, "offset": 0
}
```

Denied attempts appear with outcome `DENIED` or `ACTION_NOT_ALLOWED`. The `steps` equal what the panel showed for the run.

## Saved views and visit briefs (P1)

An agent can propose; only an approved preview is saved (FR-22). The agent role has no write privilege on any clinical table.

### `POST /views/preview`

```json
{ "kind": "VISIT_BRIEF", "patient_id": "P-1042", "content": { "answer_ids": ["ANS-0007"], "title": "Visit brief for 10 Oct" } }
```

`200` with the rendered preview and a `preview_id` valid for 10 minutes. Nothing is stored.

### `POST /views`

```json
{ "preview_id": "PV-77", "approved": true }
```

`201` with the saved view. `approved` must be `true`; otherwise `400 invalid_request`. Audited.

### `GET /views`

The caller's saved views, optionally filtered by `patient_id`.

## Admin

### `POST /admin/golden-runs` (doctor)

Starts the golden-question and routing run. It is asynchronous because 15+ agent questions can take minutes.

`202`:

```json
{ "run_id": "GR-0003", "status": "RUNNING" }
```

### `GET /admin/golden-runs/{run_id}`, `GET /admin/golden-runs/latest`

```json
{
  "run_id": "GR-0003",
  "status": "DONE",
  "started_at": "2026-10-03T09:00:00Z",
  "finished_at": "2026-10-03T09:04:40Z",
  "golden": { "total": 15, "passed": 14, "pass_rate": 0.933 },
  "routing": { "total": 25, "correct": 23, "accuracy": 0.92 },
  "results": [
    {
      "question": "Which of my patients have low eGFR?",
      "expected": "Refusal (AI-04)", "actual": "Answered with a partial list",
      "route_expected": "refuse", "route_actual": "analyst", "result": "FAIL"
    }
  ]
}
```

Failures are listed, not hidden (FR-11).

### `POST /admin/skills/{name}` (doctor, P1)

Runs a scoped CoCo skill: `evidence-audit`, `access-check`, `knowledge-ingest`. Runs under `MED_AGENT_READ` or another scoped role and returns a readable result:

```json
{ "skill": "access-check", "status": "PASSED", "summary": "S3 denied via UI route, API and Copilot; responses identical", "details": [ ... ] }
```

`404 not_found` for an unknown skill name.

## Health

### `GET /health` (Public)

Liveness only; no configuration, no credentials (NFR-08).

```json
{ "status": "ok", "version": "0.1.0" }
```

### `GET /health/details` (admin)

```json
{
  "status": "ok",
  "version": "0.1.0",
  "environment": "production",
  "snowflake": { "reachable": true, "database": "MEDYNIUM", "warehouse": "MEDYNIUM_WH", "warehouse_state": "SUSPENDED", "service_role": "MED_API" },
  "cortex": { "router_model": "llama3.1-8b", "strong_model": "claude-sonnet-4-6", "search_service": "ok", "agent": "ok" },
  "audit_writes": "ok"
}
```

`status` is `degraded` if any component fails. A suspended warehouse is normal and not a failure.
