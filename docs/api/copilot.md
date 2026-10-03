# Copilot, safety review, actions and evidence

Conventions, error codes and the SSE frame format: [README.md](README.md). Routing, answer object and validation: [../architecture/ai-layer.md](../architecture/ai-layer.md). Every call here is audited, including denials.

## `POST /patients/{patient_id}/safety-review`

The manual **Run safety review** button (FR-20). Runs the `safety` route directly, with no router.

Request: no body.

With `Accept: text/event-stream`:

```text
event: step
data: {"step_id":"s1","label":"Checking access to this patient","status":"done"}

event: step
data: {"step_id":"s2","label":"Reading medications, labs and diagnoses","status":"running"}

event: step
data: {"step_id":"s2","label":"Reading medications, labs and diagnoses","status":"done","detail":"3 medicines, 3 labs"}

event: step
data: {"step_id":"s3","label":"Searching label text","status":"done","detail":"3 sources"}

event: step
data: {"step_id":"s4","label":"Checking each statement against its evidence","status":"done","detail":"7 kept, 0 removed"}

event: answer
data: {"answer_id":"ANS-0007","kind":"safety","patient_id":"P-1042", ... }

event: done
data: {"audit_id":"AUD-000412"}
```

With `Accept: application/json`, the same run returns the answer object once finished. `404 not_found` if the patient is missing or denied (the stream is not opened). `503 agent_unavailable` and `504 timeout` are sent as an `error` event on a stream, or as the HTTP error in JSON mode; Patient 360 keeps working either way.

Expected behaviour by scenario:

| Patient | Result |
| --- | --- |
| S1 | A considerations list that includes the metformin and eGFR consideration, each statement tagged, with patient and source evidence |
| S2, S4 | "No documented consideration found in the indexed sources", what was checked, what was not indexed, and the snapshot date |
| S5 | The injected instruction is not followed; `limits.notes` says instruction-like text was treated as data |

## `POST /copilot/ask`

The agent panel and command bar. Free text is routed; the open screen and patient give context (FR-18).

Request:

```json
{
  "question": "Open the kidney-disease patient and run the safety review",
  "screen": "dashboard",
  "patient_id": null
}
```

`screen` is one of `dashboard`, `patients`, `patient`, `knowledge`, `activity`, `admin`. `patient_id` is the open patient, if any; it is never trusted as proof of access.

Stream for the example (abbreviated):

```text
event: route
data: {"route":"action","model":null,"confidence":0.93,"reason":"Navigation request","cost_note":"no model call"}

event: action
data: {"action":"open_patient","params":{"patient_id":"P-1042"},"status":"done","result":{"patient_id":"P-1042","name":"Rahul Patel"}}

event: route
data: {"route":"safety","model":"claude-sonnet-4-6","confidence":0.88,"reason":"Combines the patient's medicines with label text","cost_note":"strong model"}

event: step
data: {"step_id":"s1","label":"Reading medications, labs and diagnoses","status":"done"}

event: answer
data: { ...answer object... }

event: done
data: {"audit_id":"AUD-000413"}
```

Per-route behaviour:

| Route | Events | Notes |
| --- | --- | --- |
| `lookup` | `route`, `answer` (kind `MEDS`, `UTIL` or `LABS`), `done` | No model call after routing; answered from `ANALYTICS` |
| `analyst` | `route`, `step`, `answer`, `done` | Cortex Analyst; SQL stored as evidence |
| `knowledge` | `route`, `answer` (kind `KNOWLEDGE`: cited sections, no generated text), `done` | |
| `safety` | `route`, `step`s, `answer`, `done` | Strong model |
| `action` | `route`, `action` for each step (up to 3), `done` | Allowlist enforced; may be followed by another route's events |
| `refuse` | `route`, `refusal`, `done` | Prescribing, dosing, cross-patient, population, unlisted action, record change |

Failures: if the router is unreachable or returns invalid JSON it is retried once, then the input is handled as a question for `safety`; it is **never** turned into an action. Low confidence escalates to `safety` or asks a clarifying question (`refusal.reason = "needs_clarification"`).

`404 not_found` when the named or open patient is missing or denied, with the same body as a nonexistent one. `400 invalid_request` when `question` is empty or over 2,000 characters.

## `POST /agent/actions`

Executes one allowlisted action under the caller's session. Used by the agent panel when the router proposed an action, and by tests. It calls the same internal functions as the UI endpoints (SEC-11).

Request:

```json
{ "action": "open_patient", "params": { "patient_id": "P-1042" } }
```

| Action | `params` | Result |
| --- | --- | --- |
| `open_patient` | `patient_id` **or** `name_query` | `{ "patient_id", "name" }`. A `name_query` that matches more than one entitled patient returns `409 conflict` with the candidates' ids and names (entitled patients only). |
| `show_timeline` | `patient_id`, and `from` and `to` **or** `lab_code` | `{ "view": "timeline" \| "lab_trend", ... }` for the UI to display |
| `run_safety_review` | `patient_id` | `{ "answer_id" }` after completion (use the safety-review stream for live steps) |
| `pin_evidence` | `answer_id`, `evidence_id` | `{ "pin_id" }` |

Response `200`:

```json
{ "action": "open_patient", "status": "done", "result": { "patient_id": "P-1042", "name": "Rahul Patel" }, "audit_id": "AUD-000414" }
```

Anything else, including any request to change the clinical record, returns:

```json
{ "error": "action_not_allowed", "message": "That action is not available. The agent can open a patient, show a timeline or lab trend, run the safety review, or pin evidence." }
```

with HTTP 403, and an audit row with outcome `ACTION_NOT_ALLOWED`. A non-entitled patient returns the standard `404 not_found`.

## `GET /evidence/{answer_id}`

The **Why?** panel (FR-08). Callers can read only their own answers; anything else is `404 not_found`.

```json
{
  "answer_id": "ANS-0007",
  "patient_id": "P-1042",
  "created_at": "2026-10-03T08:42:11Z",
  "route": { "route": "safety", "model": "claude-sonnet-4-6", "confidence": 0.88 },
  "patient_records": [
    { "evidence_id": "P1", "record_type": "MEDICATION", "record_id": "RX-88231", "table": "CLINICAL.MEDICATION", "value": "Metformin 1000 mg twice daily", "date": "2026-08-14" },
    { "evidence_id": "P2", "record_type": "LAB_RESULT", "record_id": "LAB-77120", "table": "CLINICAL.LAB_RESULT", "value": "eGFR 42 mL/min/1.73 m²", "date": "2026-09-18" }
  ],
  "sql": [
    { "sql_id": "Q1", "role": "U_7f0c2f2e5b434a439a4e2f4d0d8c1a11", "text": "SELECT ...", "row_count": 6, "ran_at": "2026-10-03T08:42:03Z" }
  ],
  "sources": [
    {
      "evidence_id": "S1", "chunk_id": "CH-0412", "document_id": "DOC-MET-001",
      "title": "Metformin hydrochloride tablets: prescribing information",
      "source": "openFDA drug labeling", "section": "Warnings and precautions",
      "version": "Label version 6", "effective_date": "2026-08-12", "retrieved_date": "2026-10-02",
      "text": "Assess renal function before initiating ...", "matched": true
    }
  ],
  "statement_map": { "C1": ["P1", "P2"], "C2": ["S1"], "C3": ["P1", "P2", "S1"] },
  "dropped_statements": [],
  "snapshot_date": "2026-10-02"
}
```

`statement_map` links each consideration id in the answer to its evidence ids. The panel works without hover (NFR-10). Pinning an item uses `POST /patients/{id}/pins`.
