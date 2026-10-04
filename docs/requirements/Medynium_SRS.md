# Medynium: Software Requirements Specification

Oct 3, 2026 · Vaibhav Patel · Derived from Medynium_BRD.md (plan revised Oct 3)

## 1. Introduction

### 1.1 Purpose
This SRS says what the Medynium system must do and how it is constrained, in terms that can be built and tested. The BRD says why; this document says what, precisely. Requirement IDs (FR, AI, SEC, NFR, PLT) are the BRD's IDs and are not renumbered, so the BRD, this SRS and the test report trace to each other.

### 1.2 Scope
Medynium is a governed Patient 360 on Snowflake plus an agent-centered clinical workstation. Every statement in an AI answer links to a patient record and a source document, or the system says it found nothing. It runs on synthetic patient data and public drug-label text, as decision support only.

In scope for Oct 3: all P0 and P1 features. P2 (analyst role, native app, alerts) is out of scope.

### 1.3 Definitions

| Term | Meaning |
| --- | --- |
| Patient 360 | One entitlement-scoped view of a patient: demographics, diagnoses, medications, labs, events, utilization |
| Copilot / agent | The one Medynium Agent (a Cortex Agent behind FastAPI) |
| Why? panel | Evidence panel listing patient records, SQL and source sections for an answer |
| Entitlement | A row in `PATIENT_ENTITLEMENT` giving a user access to a patient |
| Allowlist | The closed set of actions the agent may request |
| Golden set | At least 15 questions with expected citations, used for the test report |
| S1 to S5 | Seeded scenarios: hero, control, access, gap, injection (BRD section 9) |

### 1.4 References
Medynium_BRD.md; Snowflake Cortex Analyst, Cortex Search and Cortex Agent documentation; Synthea CSV export; openFDA drug labeling.

## 2. Overall description

### 2.1 System context

```text
Browser (Next.js workstation)
   |  HTTPS, session cookie
   v
FastAPI backend  -- per-user Snowflake connection (role = doctor | assistant)
   |  tools: Cortex Agent call, SQL views, audit writer, allowlist enforcer
   v
Snowflake
   CLINICAL / KNOWLEDGE / SECURITY / ANALYTICS schemas
   Row access policies on CLINICAL and ANALYTICS
   Cortex Analyst (semantic view)  Cortex Search (document chunks)  Cortex Agent
CoCo CLI: build, test and audit tooling; not in the answer path (PLT-05)
```

### 2.2 Users

| Role | Snowflake role | Access |
| --- | --- | --- |
| Doctor | `MED_DOCTOR` | Entitled patients, Copilot, own audit trail, admin page |
| Assistant | `MED_ASSISTANT` | Only patients the doctor permits; no admin page |

Seeded users: Dr. Sharma (doctor), one assistant, one second doctor to prove cross-doctor isolation.

### 2.3 Constraints
- Snowflake trial, $400 credit; smallest warehouse, auto-suspend 60 s, resource monitor at 50% notify and 80% suspend (NFR-02).
- No outside API at run time; openFDA and others are read at ingestion only (NFR-12).
- Synthetic or public data only; banner on every patient screen (SEC-08, AI-07).
- Search index holds public documents only, never patient data (SEC-04).
- Build window is one day; hero flow first, P1 cut before it slips.

### 2.4 Assumptions to verify first
1. Cortex Agent and Analyst run under the caller's role and honor row access policies. If not, SEC-04 (no patient data in search) and API-level scoping carry the guarantee, and G4 is tested through all three layers.
2. A Cortex Agent can call FastAPI endpoints as custom tools. If not, FastAPI maps the agent's output to allowlisted actions (D7 default).
3. CoCo CLI works on the trial account.

## 3. System features

Each feature lists its requirement, behavior and acceptance test. Tiers are from the BRD.

### 3.1 Authentication and entitlements (FR-01, FR-09, SEC-01 to SEC-03, SEC-05, SEC-10, SEC-11)
- Sign-in creates a session mapped to one Snowflake role. Every query for that session runs under that role.
- Row access policies on all patient-keyed tables read `PATIENT_ENTITLEMENT` for `CURRENT_USER()`.
- The API also checks entitlement before calling Snowflake, as a second layer (D3).
- A denied patient returns exactly the response of a non-existent one: HTTP 404 with the same body and similar latency. No error text names the patient.
- Retrieval runs under the user's role first; only authorized rows reach the model context.

Test: assistant requests S3 by UI, API (`GET /patients/{id}`) and Copilot; all three return the not-found response, and an audit row exists (G4, HJ-3).

### 3.2 Workstation shell (FR-16, P0)
Fixed three-zone layout on every screen: top bar (patient search, command bar, user and role), navigation (Dashboard, Patients, Knowledge, Activity log, plus Admin for the doctor), central workspace, and a collapsible agent panel. An activity strip at the bottom shows each agent step and user action. The synthetic-data banner is always visible.

Test: collapse the agent panel; every P0 manual task still completes.

### 3.3 Dashboard (FR-17, P0)
Three widgets from precomputed views, no AI call on load:
1. Worklist of entitled patients with change indicators (new medication or lab change since last encounter).
2. Recent lab and medication changes.
3. Utilization summary.

P1: an agent briefing on request only (button, never on load).

Test: widget values equal SQL ground truth; assistant's worklist excludes S3.

### 3.4 Patient 360 (FR-02, P0)
Overview shows demographics, active diagnoses, current medications, latest labs, recent events and utilization summary. Each value shows its date and source table. Backed by `ANALYTICS.PATIENT_360`, no AI call.

### 3.5 Timeline (FR-03, P0)
Encounters, diagnoses, medication starts and changes, labs and claims merged in date order from `ANALYTICS.PATIENT_TIMELINE`. Supports a date range filter and a lab trend view. Selecting an event shows the underlying record.

### 3.6 Claims and utilization (FR-04, P0)
Counts of outpatient visits, hospitalizations and procedures; approved amounts; a claim linked to its encounter by encounter ID. Totals match a SQL check.

### 3.7 Medical knowledge search (FR-06, P0; FR-14, P1)
Search box over Cortex Search. Every result shows document ID, title, source, section, version, effective date, retrieval date, and a page number only where the source has pages. Snapshot date is shown with results. P1 adds a small regulatory set under the same behavior.

Test: each seeded drug returns its expected label section.

### 3.8 Copilot (FR-05, FR-18, P0)
- Answers structured questions (summary, what changed, current medications, utilization) from Cortex Analyst; simple lookups use plain SQL with no AI call.
- Context-aware: it receives the open screen and patient, answers for that patient without being told the name, and states the patient in scope in the panel.
- Refuses cross-patient and population questions (AI-04).

### 3.9 Hybrid safety review (FR-07, P0)
Runs the Cortex Agent over the patient's medications, labs and diagnoses (via Analyst) and label text (via Search). Output follows the fixed structure in section 6. Available as the agent request "run safety review" and as a manual "Run safety review" button (FR-20).

Test: S1 returns the renal consideration with patient and source evidence; S2 and S4 return "no documented consideration found in the indexed sources" with what was checked; S5's injected instruction is not followed.

### 3.10 Evidence ("Why?") panel (FR-08, P0)
Opens from any answer, from the agent panel or the workspace. It lists:
- Patient records: record IDs, type, date
- The SQL that ran
- Source documents: title, source, section, version, effective date, retrieval date

Each answer statement carries a tag (AI-09) and maps to at least one evidence item. Unmapped statements are removed before display (AI-02). Works without hover (NFR-10).

### 3.11 Agent actions and manual parity (FR-19, FR-20, FR-21, P0)
Allowlist of four actions, enforced on the server (SEC-12):

| Action | Params | Manual equivalent |
| --- | --- | --- |
| `open_patient` | patient_id or name query | Click worklist row or use patient search |
| `show_timeline` | patient_id, date range or lab code | Timeline filter and lab trend control |
| `run_safety_review` | patient_id | "Run safety review" button |
| `pin_evidence` | answer_id, evidence_id | Pin icon in the Why? panel |

Rules: an unlisted action or any request to edit or delete an existing record is refused with an explanation and logged (AI-10). Adding a note, allergy, diagnosis or medicine, raising a finding or deciding the one open finding is prepared as a preview; only the clinician's Approve click saves it, through the same service and checks as the manual screen. The agent uses the user's session and the same endpoints as the UI (SEC-11). Steps stream into the panel as they happen, can be dismissed, and match the audit entry for the run (FR-21, AI-12). A checklist in the repo maps each action to its control.

### 3.12 Saved views and visit brief (FR-22, P1)
The agent can propose a saved view or visit brief. The UI shows a preview and the item is written to `SAVED_VIEW` only after the user approves. The agent's role has no write privilege on any clinical table.

### 3.13 Audit log (FR-10, SEC-09, P0)
Every Copilot query and every agent action writes to `COPILOT_AUDIT`: user, role, action, patient, question, answer ID, patient evidence IDs, retrieved document IDs, agent steps, outcome, time. Denied attempts are logged. The doctor sees their own entries in the Activity log page.

### 3.14 Golden-question test report (FR-11, NFR-06, P0)
An on-demand run of at least 15 questions. The report lists each question, expected citation, actual citation and result, including failures, with the overall pass rate. It covers all seeded scenarios, an AI-01 prescribing prompt, an AI-04 cross-patient prompt and an AI-06 conflict pair.

### 3.15 Admin page and CoCo skills (FR-12, PLT-03, PLT-04, P1)
Doctor-only page that runs: evidence audit, access check, and (if time remains) knowledge ingest. Each runs under a read-only or scoped role and returns a readable result. Also shows corpus status, snapshot date and the latest golden report.

### 3.16 Responsive layout (FR-13, P1)
Patient list, Patient 360 and Copilot work at 390 px width. At that width the agent panel becomes a bottom sheet.

## 4. External interfaces

### 4.1 User interface
Next.js responsive web app. Required screens: Sign-in, Dashboard, Patient list, Patient workspace (Overview, Timeline, Medications, Labs, Claims tabs), Knowledge search, Why? panel, Activity log, Admin. Required states for every data screen: loading with progress, empty, error with retry, and agent-unavailable (workspace stays usable, NFR-09, NFR-13).

### 4.2 REST API (FastAPI)
All endpoints require a session except `/auth/login` and `/health`. Responses are JSON; the agent endpoint streams server-sent events.

| Method and path | Purpose | Notes |
| --- | --- | --- |
| `POST /auth/login`, `POST /auth/logout`, `GET /me` | Session and role | |
| `GET /dashboard` | Three widgets | No AI call |
| `GET /dashboard/briefing` | Agent briefing | P1, on request |
| `GET /patients` | Entitled worklist | Search by `q` |
| `GET /patients/{id}` | Patient 360 overview | 404 if denied or absent |
| `GET /patients/{id}/timeline` | Timeline | `from`, `to` |
| `GET /patients/{id}/labs/{code}/trend` | Lab trend | |
| `GET /patients/{id}/claims` | Claims and utilization | |
| `POST /patients/{id}/safety-review` | Hybrid safety answer | Returns `answer_id` |
| `POST /copilot/ask` | Free question about the open patient | SSE stream |
| `POST /agent/actions` | Execute one allowlisted action | Server rejects others |
| `GET /evidence/{answer_id}` | Why? panel data | |
| `GET /knowledge/search` | Label and guideline search | |
| `POST /views/preview`, `POST /views` | Preview then save a view | P1; save needs `approved: true` |
| `GET /audit` | Caller's own audit entries | |
| `POST /admin/golden-run`, `POST /admin/skills/{name}` | Test report and CoCo skills | Doctor only, P1 for skills |
| `GET /health` | Active role, database, warehouse, agent | No credentials (NFR-08) |

Error contract: `{ "error": code, "message": text }`. Codes: `not_found`, `unauthorized`, `action_not_allowed`, `agent_unavailable`, `timeout`.

### 4.3 Snowflake interfaces
Python connector per user with role switch; Cortex Analyst via a semantic view with verified queries; Cortex Search service over `KNOWLEDGE.DOCUMENT_CHUNK`; Cortex Agent defined with the Analyst and Search tools.

### 4.4 Data ingestion interfaces
Synthea CSV loaded to CLINICAL (D6); openFDA drug label JSON loaded to KNOWLEDGE at ingestion only; seed scripts for users, entitlements, notes and S1 to S5. All scripts idempotent (NFR-07).

## 5. Data requirements

| Schema | Tables and views |
| --- | --- |
| CLINICAL | `PATIENT`, `ENCOUNTER`, `DIAGNOSIS`, `MEDICATION`, `LAB_RESULT`, `PROCEDURE`, `CLAIM`, `CLINICAL_NOTE` |
| KNOWLEDGE | `DOCUMENT`, `DOCUMENT_CHUNK`, `DRUG`, `DRUG_NAME_MAP`, `EVIDENCE` |
| SECURITY | `APP_USER`, `ROLE`, `PATIENT_ENTITLEMENT`, row access policies |
| ANALYTICS | `PATIENT_360`, `PATIENT_TIMELINE`, `UTILIZATION`, `CURRENT_MEDICATIONS`, `DASHBOARD_WORKLIST`, `COPILOT_AUDIT`, `SAVED_VIEW` |

Key rules:
- Units, dates and reference ranges normalized on load; encounter, procedure and claim IDs preserved so a claim joins to its encounter.
- `DOCUMENT` and `DOCUMENT_CHUNK` record document ID, source, type, drug, section, version date and ingestion date.
- `DRUG_NAME_MAP` links Synthea medication names to label names for the 20 to 30 in-scope drugs; seeded medications come from that list.
- ANALYTICS views are built at load time (NFR-11).
- Corpus: 20 to 30 drugs, 100 to 300 chunks, indexed once (NFR-04). Patients: a few hundred, plus S1 to S5 hand-seeded; about 20 generated notes.

## 6. AI behavior specification

### 6.1 Answer structure (AI-08, AI-09)
Every Copilot answer is returned as JSON and rendered as:

```text
short_answer: string
considerations: [
  { text, tag: patient_fact | retrieved_source | ai_synthesis,
    patient_evidence: [record ids], source_evidence: [chunk ids] }
]
limits: what was checked, what is indexed, snapshot date
```

Rendering rules:
- A `retrieved_source` statement shows section and version. A `patient_fact` shows value and date. An `ai_synthesis` statement is worded "may warrant clinician review".
- Statements with empty evidence are dropped by the backend validator before display.
- If no source evidence exists: "No documented consideration found in the indexed sources", never "no risk" (AI-03), plus the list of checked drugs and the snapshot date.
- If two sources conflict, both are listed with version and date (AI-06).
- Prompts asking for diagnosis, treatment or dosing return a scoped refusal plus the relevant documented considerations (AI-01).
- Text in labels or notes is treated as data; embedded instructions are ignored (AI-05).

### 6.2 Safeguards in order
1. API resolves patient and checks entitlement.
2. Agent runs under the user's role; Analyst and Search results are collected.
3. Backend validator checks that each statement maps to evidence and its tag matches the evidence type.
4. Answer, steps and evidence IDs are stored and audited.
5. UI shows the synthetic-data banner.

## 7. Non-functional requirements

Targets are from the BRD and are validated before the demo.

| Area | Requirement | Verification |
| --- | --- | --- |
| Performance | Patient list and 360 under 3 s; hero answer p50 under 20 s with progress (NFR-01, G5) | Timed run on the deployed stack |
| Cost | Warehouse settings and resource monitor per NFR-02; spend under $400 (G6) | Monitor screenshot |
| AI use | AI only for Copilot questions; few chunks to the model (NFR-03) | Code review |
| Auditability | Any answer is reproducible from stored SQL, record IDs, chunk IDs and source version (NFR-05) | Replay one answer |
| Resilience | Agent failure shows a clear error and Patient 360 still works (NFR-09, NFR-13) | Kill the agent call |
| Accessibility | Keyboard reach, readable contrast, no hover-only content (NFR-10) | Manual check |
| Reproducibility | Idempotent setup scripts and a README (NFR-07) | Fresh run on a clean schema |
| Security | Least privilege, no admin role at run time, no committed secrets, `.env.example` only (SEC-06, SEC-07) | Role grants review |

## 8. Verification

| Check | Covers | Evidence |
| --- | --- | --- |
| Golden-question run | FR-05 to FR-08, FR-11, AI-01 to AI-09, G1 to G3 | Pass-rate report with failures |
| Access check | FR-01, FR-09, SEC-02, SEC-05, SEC-10, G4 | UI, API and Copilot denial of S3; audit rows |
| Hero journeys HJ-1 to HJ-5 | Acceptance scenarios | Demo video |
| Agent allowlist check | FR-19, SEC-11, SEC-12, AI-10, AI-11 | Unlisted action and record-change prompts refused |
| Step-log match | FR-21, AI-12 | Panel steps equal audit entry |
| Manual parity checklist | FR-20, G7 | Action-to-control table |
| Timing and cost | NFR-01, NFR-02, G5, G6 | Timings, credit usage |

## 9. Requirement traceability

| BRD goal | SRS feature | Verified by |
| --- | --- | --- |
| G1 hero answer with evidence | 3.9, 3.10 | Golden set, HJ-1 |
| G2 honest control | 3.9, 6.1 | S2, S4, HJ-4 |
| G3 golden set at least 15 | 3.14 | Test report |
| G4 assistant denied | 3.1 | Access check, HJ-3 |
| G5 speed | 3.8, 3.9, NFR-01 | Timed run |
| G6 cost | NFR-02 | Resource monitor |
| G7 manual parity | 3.11 | Checklist, HJ-5 |
| G8 visible and logged steps | 3.11, 3.13 | Step-log match |

## 10. Open items to close before building

| # | Item | Default if not decided |
| --- | --- | --- |
| D2 | Guideline documents | Labels only; add a small regulatory set for FR-14 if licence allows |
| D3 | User to role mapping | Two roles plus API scoping |
| D4 | Run-time CoCo skills | Evidence audit and access check; knowledge ingest if time remains |
| D5 | Document parsing | Skip; openFDA text is already structured |
| D7 | Action orchestration | FastAPI maps agent output to the allowlist |
| D8 | Agent autonomy | Reads and navigation only; saves behind confirmation |
