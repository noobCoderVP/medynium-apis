# Medynium: Business Requirements Document

Oct 2, 2026 (plan revised Oct 3) · Vaibhav Patel

## 1. Executive summary

Medynium lets a clinician ask one question about a patient and get an answer in which every statement links to a patient record and a source document. It is our entry for Problem Statement 4 (Patient and Member 360 and Clinical or Regulatory Document Copilot) in the Snowflake CoCo CLI Hackathon 2026, GCC Edition.

**The claim:** every AI insight is traceable to patient-specific evidence and to authoritative medical evidence, and the system says so plainly when it has neither.

**What it is:** a governed Patient 360 on Snowflake, plus an agent-centered workstation: a dashboard and patient workspace that can be used by hand, and an agent that combines structured patient data (Cortex Analyst) with a curated drug-label and guideline corpus (Cortex Search) through a Cortex Agent. A FastAPI backend and a web client sit in front, and the agent calls the same API as the UI. CoCo CLI is used to build, test and audit the system.

**What it is not:** a diagnosis or treatment tool. It surfaces documented considerations for clinician review, on synthetic patient data only.

**Oct 3 build:** every P0 and P1 feature is built and working by end of day on Oct 3. Oct 4 is held for testing, the demo video and submission only, with no new features. P2 items stay roadmap. The core is one hero workflow in the workstation, end to end. From the dashboard, open a patient by click or by asking the agent, ask the safety question, read the answer, click "Why?", and show an assistant being denied a patient the doctor can see.

## 2. Problem and opportunity

Clinicians lose time and trust because patient facts and medical knowledge live in different places, and AI answers that cannot show their sources are not usable in care settings.

| Problem | What it looks like | What Medynium does |
| --- | --- | --- |
| Fragmented patient data | EHR, labs, medications, claims and documents sit in separate systems | One governed Patient 360 and timeline in Snowflake |
| Buried information | Long records, drug labels, guidelines and safety documents | Cortex Search over a curated corpus, with section-level sources |
| Hard to connect facts to knowledge | "Is this medication relevant given this patient's recent history?" | A Cortex Agent that retrieves patient facts and label text together |
| Unverifiable AI | An answer with no way to check where it came from | A "Why?" panel with patient records, SQL, source section, version and date |

**Why Snowflake is the center:** structured data, document search, an agent and row-level governance live on one platform. Patient data never has to be copied into a separate vector store or orchestration service, which also keeps the $400 trial budget under control.

**Why this track:** the brief asks for a patient or member 360 that answers clinical, safety or regulatory questions with cited evidence, using only synthetic or de-identified data. Medynium is built around exactly that.

## 3. Goals, success criteria and non-goals

We succeed if the hero workflow runs end to end on the deployed system with verifiable evidence, because the rubric weights technical execution at 40%, real-world relevance at 30% and solution completeness at 30%.

| Rubric criterion | Weight | What we must be able to show |
| --- | --- | --- |
| Technical execution | 40% | Cortex Analyst, Search and Agent working together; per-user access control that also binds the AI; CoCo CLI session logs and skills |
| Real-world relevance | 30% | A clinician workflow with a seeded, realistic safety scenario and honest handling of missing evidence |
| Solution completeness | 30% | A deployed app, a working "Why?" panel, an audit log, a test report and a demo video |

**Measurable goals (targets, to be validated before the demo)**

- G1: the hero question returns an answer with at least one patient fact and one source section for every seeded risk patient.
- G2: a control patient with no matching label content returns "no documented consideration found in the indexed sources", never a guess.
- G3: a golden set of at least 15 questions passes with correct citations; the pass rate is shown, including failures.
- G4: an assistant account is denied a patient the doctor can see, through the UI, the API and the Copilot.
- G5: p50 time to answer the hero question is under 20 seconds, with visible progress while waiting.
- G6: total Snowflake spend stays under the $400 trial credit, with a resource monitor in place.
- G7: every agent action has a manual equivalent, and the hero task can be completed by hand (HJ-5).
- G8: every agent step is visible in the panel and recorded in the audit log, and the agent can act only on its allowlist.

**Non-goals**

- Autonomous diagnosis, treatment or dosing recommendations
- Patient-facing features
- Claims submission, adjudication or fraud detection
- Real hospital integration or real patient data
- Streaming pipelines, large datasets or a second AI orchestration platform
- Background or unprompted agent actions, and any agent write to the clinical record

## 4. Users, personas and roles

Medynium serves healthcare professionals only; the demo needs two roles working, and two more can be described as roadmap.

| Role | Who | What they can do | Oct 4 cut |
| --- | --- | --- | --- |
| Doctor / clinician | Reviews assigned patients | Full Patient 360, Copilot, evidence, own audit trail | Yes |
| Assistant / nurse | Prepares visits for a doctor | Patient 360 limited to the doctor's permitted patients; summaries and "what changed"; no access to patients outside entitlement | Yes |
| Clinical / regulatory analyst | Studies safety and regulatory content | De-identified patient aggregates and the medical knowledge base | Roadmap |
| System admin | Manages access and configuration | Users, roles, entitlements, corpus status, quality report | Minimal (seeded users) |

**Primary persona:** Dr. Sharma, a general physician with a morning list of assigned patients. She has a few minutes per patient and needs to know what changed, what is on the medication list, and whether anything in the record deserves a second look.

**Secondary persona:** a clinic assistant preparing her list. Useful on the same screens, but must never see a patient who is not assigned to Dr. Sharma.

## 5. Product concept: the workstation

Medynium is a clinical workstation: a dashboard and patient workspace the user can drive by hand, with an AI agent beside them that does the same work on request. In this BRD "Copilot" and "agent" mean the same Medynium Agent; requirement IDs keep the Copilot wording.

Workstation layout (text rendering of the diagram in the online doc):

```text
+--------------------------------------------------------------------------+
| Top bar: patient search, command bar (ask or do), user and role          |
+------------+-------------------------------------+-----------------------+
| Navigation | Workspace                           | Agent panel           |
|  Dashboard |  Dashboard: worklist, changes,      |  Ask in plain language|
|  Patients  |   briefing                          |  Sees the open patient|
|  Knowledge |  Patient: overview, timeline,       |  Runs allowed actions |
|  Activity  |   labs, claims                      |  Shows steps and Why? |
|  log       |  Evidence panel opens from Why?     |  Same API as the UI   |
|            |  Opened by click or by the agent    |                       |
+------------+-------------------------------------+-----------------------+
| Activity strip: every agent step and user action goes to the audit log   |
+--------------------------------------------------------------------------+
```

The navigation and workspace are fully usable without the agent; the agent panel sees the open patient, calls the same API as the UI, and shows every step it takes.

**Design principles**

- **Agent-centered, manual-capable:** the agent is the fastest path for a task, and every task it can do has a manual control.
- **Same API, same rules:** agent actions call the same endpoints as the UI, so entitlements, validation and audit apply identically.
- **Closed action set:** the agent can only do what is on an allowlist. For Oct 4 that is: open a patient, show a timeline range or lab trend, run the safety review, and pin evidence to the workspace.
- **Human in control:** agent steps are visible and can be dismissed. Anything beyond navigation and read-only views asks for confirmation. The agent never writes to the clinical record by itself and never acts unprompted: it can prepare a new note, allergy, diagnosis or medicine, or a finding decision, as a preview, and nothing is saved until the clinician approves it.
- **Evidence everywhere:** every agent answer keeps its "Why?" panel, and evidence opens the same way from the agent panel or the workspace.

| Mode | Who drives | Example | Oct 4 |
| --- | --- | --- | --- |
| Manual | The user clicks, searches and filters | Opens a patient from the worklist and scrolls the timeline | Yes |
| Assisted | The user works and asks the agent a question | "What changed since the last visit?" with the patient open | Yes |
| Agent-led | The user states a goal; the agent runs allowed actions and shows its steps | "Open the kidney-disease patient and run the safety review" | Yes, four actions |
| Autonomous | The agent acts in the background without being asked | Not offered | No |

## 6. Scope

By end of Oct 3 we build one responsive web app and one backend with all P0 and P1 capabilities; P2 items are designed but not built. The React Native app is roadmap, shown as screens in the UX prototype. Decision D1: the responsive web app is built first and migrated to native later.

| Capability | Tier | Oct 4 cut |
| --- | --- | --- |
| Patient list scoped by entitlement | P0 | Build |
| Patient 360 overview (conditions, medications, labs, recent events) | P0 | Build |
| Timeline from structured data | P0 | Build |
| Claims and utilization summary, linked to encounters | P0 | Build, small |
| Copilot for structured questions (summary, what changed, current medications) | P0 | Build |
| Medical knowledge search over a curated corpus | P0 | Build |
| Hybrid safety question (patient facts plus label text) | P0 | Build |
| Evidence explorer ("Why?") | P0 | Build |
| Entitlement demo including the AI layer | P0 | Build |
| Audit log and golden-question test report | P0 | Build |
| CoCo CLI used at build and test | P0 | Build |
| Admin page with run-time CoCo skills (FR-12) | P1 | Build |
| Mobile-friendly layout | P1 | Build, responsive |
| Regulatory document search | P1 | Build, small set |
| Analyst role with de-identified view | P2 | Roadmap |
| Native point-of-care app, migrated from the web app | P2 | Roadmap, shown as designs |
| Alerts and review queue | P2 | Roadmap |
| Workstation shell (top bar, navigation, workspace, agent panel) | P0 | Build, fixed layout |
| Dashboard with worklist and recent changes | P0 | Build, three widgets from precomputed views |
| Context-aware agent with four allowed actions | P0 | Build |
| Manual control for every agent action | P0 | Build |
| Agent briefing on the dashboard | P1 | Build, on request |
| Save a view or visit brief with confirmation | P1 | Build, behind confirmation |

**Corpus size:** 20 to 30 drugs and 100 to 300 document chunks, indexed once.

**Patient data size:** a few hundred synthetic patients, with a handful hand-seeded for the demo scenarios in section 9.

## 7. Functional requirements

Each requirement has an ID, a tier and an acceptance test, so the demo and the test report can be checked against this table.

| ID | Requirement | Tier | Acceptance criteria |
| --- | --- | --- | --- |
| FR-01 | Patient list shows only patients the signed-in user is entitled to | P0 | Doctor sees assigned patients; assistant sees only the doctor's permitted subset |
| FR-02 | Patient 360 overview: demographics, active diagnoses, current medications, latest labs, recent events, utilization summary | P0 | All fields come from Snowflake views; each value shows its date and source table |
| FR-03 | Timeline merges encounters, diagnoses, medication starts and changes, labs and claims in date order | P0 | Events are ordered correctly; selecting an event shows its underlying record |
| FR-04 | Claims and utilization: counts of outpatient visits, hospitalizations and procedures, approved amounts, and the claim linked to an encounter | P0 | Totals match a SQL check; at least one encounter shows its linked claim |
| FR-05 | Copilot answers structured questions (summary, what changed since last visit, current medications, utilization) | P0 | Answers match SQL ground truth on the golden set; no AI call for simple lookups |
| FR-06 | Medical knowledge search over the curated corpus with document ID, title, source, section, version, effective date and retrieval date on every result; a page number only where the source has pages | P0 | Search returns the expected label section for each seeded drug |
| FR-07 | Hybrid safety question combines the patient's medications, labs and diagnoses with label text | P0 | Seeded risk patients get the expected consideration; a control patient gets "no documented consideration found in the indexed sources" |
| FR-08 | "Why?" evidence panel for every Copilot answer: patient records (IDs and dates), the SQL that ran, and source documents (title, source, section, version, effective date, retrieval date) | P0 | Each statement in the answer maps to at least one listed evidence item; an unmapped statement fails the test |
| FR-09 | Entitlements apply to the UI, the API and the Copilot | P0 | An assistant asking about a non-entitled patient gets the same response as for a non-existent patient |
| FR-10 | Audit log of every Copilot query: user, action, patient, question, answer ID, patient evidence IDs, retrieved document IDs, time | P0 | Each hero run appears in the log and the log is visible to the doctor for their own queries |
| FR-11 | Golden-question test run with a pass rate report | P0 | Report lists each question, expected citation, actual citation and result, including failures |
| FR-12 | CoCo skills callable from an admin page: evidence audit, access check, knowledge ingest | P1 | Each skill runs with a read-only or scoped role and returns a readable result |
| FR-13 | Responsive layout usable on a phone | P1 | Patient list, Patient 360 and Copilot work at a 390 px width |
| FR-14 | Regulatory document search | P1 | Same behavior as FR-06 over a small regulatory set |
| FR-15 | Analyst role with de-identified aggregates | P2 | Roadmap |
| FR-16 | Workstation shell: top bar, navigation, central workspace and agent panel on every screen; the agent panel can be collapsed and the product stays fully usable without it | P0 | Every screen shows the shell; with the agent panel collapsed, every P0 manual task can still be completed |
| FR-17 | Dashboard: entitled patient worklist with change indicators, recent lab and medication changes, and a utilization summary | P0 | Widgets match SQL ground truth and are scoped by entitlement; no AI call is made to load the dashboard |
| FR-18 | Context-aware agent: it knows the open screen and patient, defaults questions to that patient and states which patient it is using | P0 | A question asked on a patient screen is answered for that patient without naming them; the panel shows the patient in scope |
| FR-19 | Agent actions from a closed allowlist: open a patient, show a timeline range or lab trend, run the safety review, pin evidence to the workspace | P0 | Each action goes through the same API and entitlement check as the UI; an action outside the list is refused with an explanation |
| FR-20 | Manual parity: every agent action has a manual control (search, click, filter or button) | P0 | A checklist maps each action to its control; HJ-5 completes the hero task by hand |
| FR-21 | Agent steps are visible and recorded: tools called, data retrieved and result, shown in the panel and written to the audit log | P0 | Every agent run lists its steps, and the audit log has a matching entry |
| FR-22 | Confirmation for non-read actions: saving a view or visit brief shows a preview and needs approval; the agent never writes to clinical records on its own; a change it prepares is saved only after the clinician approves a preview | P1 | Saved items appear only after approval; no clinical table is writable by the agent's role |

## 8. AI behavior and clinical safety

The Copilot may only state what it can point to; when it cannot point to anything, it says so.

| ID | Rule | How we test it |
| --- | --- | --- |
| AI-01 | Decision support only: no diagnosis, no treatment choice, no dosing instruction. Language is "documented consideration for clinician review". | Prompts asking "what should I prescribe?" return a scoped refusal plus the relevant documented considerations |
| AI-02 | Every statement is backed by a retrieved patient record or a retrieved source section. Unbacked statements are removed before display. | Golden set checks that each statement maps to evidence |
| AI-03 | No evidence found is stated as "not found in the indexed sources", never as "no risk". The answer also shows what is indexed and as of when. | Control patient and a drug missing from the corpus |
| AI-04 | Patient scope: one patient per question. The Copilot refuses cross-patient and population questions from the clinician role. | Cross-patient prompt returns a refusal |
| AI-05 | Source text is data, not instructions. Text inside labels or notes that tells the model what to do is ignored. | One seeded document contains an injected instruction; the answer must not follow it |
| AI-06 | Conflicts are shown, not resolved: if two sources differ, both are listed with their versions and dates. | Seeded pair of differing sources |
| AI-07 | A visible banner states that data is synthetic and the output is decision support for a prototype. | Visual check |
| AI-08 | Answers use a fixed structure: short answer, considerations (each with patient evidence and source evidence), limits of what was checked. | Format check in the golden set |
| AI-09 | Every statement is tagged as one of three types: patient fact (a record value with its date), retrieved source (text from a document, with section and version), or AI synthesis (a conclusion combining them, worded as "may warrant clinician review"). | Golden set checks that each tag matches the evidence type shown in the "Why?" panel |
| AI-10 | The agent acts only through an allowlist of actions and only on request. It never acts in the background. It writes to the clinical record only as a proposal the clinician approves (amended by the agentic upgrade). | Prompts asking for an unlisted action or a record change are refused and logged |
| AI-11 | The agent can do nothing the signed-in user could not do by hand, and it states which patient and action it is using. | An assistant session cannot trigger an action on a non-entitled patient |
| AI-12 | Agent steps appear as they happen and can be dismissed; an answer never hides which tools produced it. | The steps shown match the audit log entry for the same run |

## 9. Data requirements

Patient data is synthetic, medical knowledge is real and public, and the demo depends on a few hand-seeded patients that make the evidence visible.

| Dataset | Source | Use | Size |
| --- | --- | --- | --- |
| Patients, encounters, conditions, medications, observations, procedures | Synthea synthetic data (CSV export) | Patient 360, timeline, Copilot facts | A few hundred patients |
| Claims | Synthea claims and payer exports, so claims link to encounters | Utilization and clinical-to-claims link | Matches patients |
| Clinical notes and discharge summaries | Generated by us | Document view and one injection test | About 20 |
| Drug labels | openFDA drug labeling | Medical knowledge search | 20 to 30 drugs |
| Guidelines and regulatory documents | To be chosen, public and license-checked | Knowledge search, P1 | A handful |
| Users, roles, entitlements | Generated by us | Access control demo | 3 to 5 users |

**Seeded scenarios (must exist before the demo)**

- S1, hero: a patient with chronic kidney disease, a reduced kidney function lab and a medication whose label has a documented renal consideration.
- S2, control: a patient on common medications with no matching label consideration in the corpus.
- S3, access: a patient assigned to the doctor but not to the assistant.
- S4, gap: a patient on a drug that is not in the indexed corpus, to show the "not found" behavior.
- S5, injection: a document containing an instruction aimed at the model.

**Data model:** four schemas. CLINICAL (patient, encounter, diagnosis, medication, lab result, procedure, claim). KNOWLEDGE (document, document chunk, drug, evidence). SECURITY (user, role, patient entitlement). ANALYTICS (patient 360, timeline, utilization, current medications). Two tables are added to the earlier design: `COPILOT_AUDIT` and `DRUG_NAME_MAP`.

**Drug name mapping:** Synthea medication names and label names differ, so a mapping table links them for the 20 to 30 drugs in scope. The Synthea medications chosen for seeding must come from that list.

**Canonical model and ingestion:** external data is normalized into the CLINICAL schema once, never queried live. For Oct 4 we load Synthea's CSV export rather than parsing FHIR. Units, dates and reference ranges are normalized on load, and encounter, procedure and claim IDs are kept so a claim links to its encounter.

**Source versioning:** the knowledge base is a controlled snapshot, not a live feed. Every document records its document ID, source, document type, drug name, section, label or publication version date, and ingestion date, in the `DOCUMENT` and `DOCUMENT_CHUNK` tables. The UI shows the snapshot date wherever evidence appears, and the system never claims to hold the latest information, only what was indexed.

**No outside API at run time:** openFDA and any other source are read during ingestion only, so an outside outage cannot affect the demo.

## 10. Security, privacy and entitlements

The AI must never be an authorization loophole: whatever a user cannot open in the app, the Copilot cannot retrieve for them either.

| ID | Requirement |
| --- | --- |
| SEC-01 | Users sign in to the API; each API session maps to one Snowflake role for that user type (doctor, assistant). |
| SEC-02 | Patient-level access is enforced in Snowflake with row access policies driven by the `PATIENT_ENTITLEMENT` table, not only in application code. |
| SEC-03 | Copilot queries run under the calling user's role. A shared service account that can see every patient must not serve Copilot requests. |
| SEC-04 | Patient data is reached only through Analyst and SQL. The Cortex Search index holds public documents only, so it contains no patient information. |
| SEC-05 | A denied patient request returns the same response as a non-existent patient, so existence is not leaked. |
| SEC-06 | Runtime roles are least-privilege. No runtime path uses an administrator role. CoCo skills called at run time use read-only or scoped roles. |
| SEC-07 | Secrets and credentials are never committed; the repository contains an example environment file only. |
| SEC-08 | All data is synthetic or public. A banner states this on every screen that shows patient data. |
| SEC-09 | Every Copilot request is audited (FR-10). |
| SEC-10 | Unauthorized patient data never reaches the model: retrieval runs under the user's role first, and only its authorized results are placed in the model context. |
| SEC-11 | Agent actions use the user's own session and the same API endpoints as the UI; there is no separate agent credential with wider access. |
| SEC-12 | The agent's action allowlist is enforced on the server, not only in the prompt; an action not on the list is rejected by the API. |

**Assumption to verify:** whether Cortex Agents and Analyst honor row access policies for the calling role in our setup. Until this is confirmed in a test, SEC-04 and the denied-patient test (G4) carry the access guarantee.

## 11. Non-functional requirements

The system must be fast enough to demo live, cheap enough for a $400 trial, and reproducible by a judge or a teammate from the repository.

| ID | Area | Requirement (targets to validate) |
| --- | --- | --- |
| NFR-01 | Performance | Patient list and Patient 360 load in under 3 seconds; the hero answer arrives in under 20 seconds with visible progress states |
| NFR-02 | Cost | Smallest suitable warehouse, auto-suspend at 60 seconds, a resource monitor with a notification threshold at 50% of credits and a suspend threshold at 80% |
| NFR-03 | AI use | AI is called only for Copilot questions; lookups, timeline and totals are plain SQL; only a few retrieved chunks go to the model, never whole records |
| NFR-04 | Indexing | The knowledge index is built once and not rebuilt during the hackathon |
| NFR-05 | Auditability | Every answer can be reproduced from its stored evidence: SQL, record IDs, chunk IDs, source version |
| NFR-06 | Quality | Golden-question suite runs on demand and its result is shown in the admin page |
| NFR-07 | Reproducibility | Idempotent setup scripts create the schemas, load data, build the search service and agent; a README lists the steps |
| NFR-08 | Observability | A health endpoint reports the active role, database, warehouse and agent without exposing credentials |
| NFR-09 | Resilience | If the agent call fails or times out, the UI shows a clear error and the structured Patient 360 still works |
| NFR-10 | Accessibility | Keyboard-reachable controls and readable contrast; evidence panel works without hover |
| NFR-11 | Precomputation | Patient 360, timeline, utilization and current-medication views are built at load time, so page loads do not recompute joins |
| NFR-12 | Dependencies | No outside API is called at run time; openFDA and every other source are read at ingestion only |
| NFR-13 | Responsiveness | Manual navigation never waits on the agent: the panel streams its steps, and a slow or failed agent call leaves the workspace usable |

## 12. Platform requirements

Snowflake is the system of record and the AI platform; the API only brokers each user's role, and CoCo CLI builds, tests and audits the stack.

Architecture (text rendering of the diagram in the online doc):

```text
Workstation (Next.js): dashboard, patient workspace, agent panel
        |
        v
FastAPI backend: sign-in, role per user, agent tools, evidence, audit log  <--->  CoCo CLI
        |                                                                     (build and test the stack,
        v                                                                      evidence audit skill,
Snowflake                                                                      access check skill)
  Row access policies, entitlements and audit log
  Cortex Agent: joins patient facts and sources
     |-> Cortex Analyst (patient facts via semantic view) -> Clinical tables and views
     |-> Cortex Search (drug labels and guidelines)       -> Knowledge: document chunks
```

Patient facts flow through Cortex Analyst, medical sources through Cortex Search, and the Cortex Agent joins them; row access policies apply to every query.

| Product feature | Snowflake capability |
| --- | --- |
| Patient 360, timeline, claims, labs | Tables, views and SQL; no AI call |
| Structured Copilot | Cortex Analyst over a semantic view with verified queries |
| Medical knowledge | Cortex Search over curated document chunks, indexed once |
| Hybrid Copilot | Cortex Agent combining Analyst and Search |
| Entitlements | Row access policies driven by a patient entitlement table |
| Evidence and audit | Evidence and `COPILOT_AUDIT` tables |
| Dashboard widgets and worklist | Precomputed views and SQL; no AI call |

| ID | CoCo CLI requirement |
| --- | --- |
| PLT-01 | Plan: an AGENTS.md describes the project, schemas and rules so every CoCo session starts from the same context |
| PLT-02 | Build: schemas, data load, semantic view, search service, agent, roles and policies are created through CoCo sessions; session logs are kept as evidence |
| PLT-03 | Test: a custom skill runs the golden questions and reports citation accuracy; an access-check skill proves the denied-patient case |
| PLT-04 | Run: an admin page calls the evidence-audit and access-check skills under scoped roles (P1, FR-12) |
| PLT-05 | CoCo is not in the doctor's answer path; the Cortex Agent serves that |
| PLT-06 | Agent actions: FastAPI exposes the UI's endpoints as the agent's tools and enforces the allowlist, while the Cortex Agent handles retrieval and answers. To verify: whether the Cortex Agent can call these as custom tools, or whether FastAPI maps its output to actions. |

## 13. Hero journeys and acceptance scenarios

The three-minute demo runs HJ-1 to HJ-3 in order; HJ-4 is the honesty check that separates a trustworthy system from a confident one. HJ-5 shows the same task done by hand, which proves manual parity.

**HJ-1: Evidence-linked safety review (hero)**

1. Dr. Sharma signs in and lands on the dashboard: her assigned patients, recent changes and the agent's briefing.
2. She asks the agent to open the seeded kidney-disease patient (S1), or clicks the patient; the workspace shows the Patient 360 and timeline.
3. She asks: "Are there documented safety considerations relevant to this patient's current medications and recent history?"
4. Medynium shows the agent's steps as it works, then a structured answer with the consideration and its limits.
5. She clicks "Why?" and sees the patient evidence (medication, lab with date, diagnosis), the SQL that ran, and the source sections (title, section, version, effective date).

Accepted when: the answer names the consideration, and every statement maps to an evidence item in step 5.

**HJ-2: What changed since the last visit**

1. On the same patient she asks what changed since the previous visit.
2. The answer lists new medications, lab changes and events, each with its date.

Accepted when: the list matches a SQL comparison of the last two encounters.

**HJ-3: Access denied for the assistant**

1. The assistant signs in and opens the patient list; the S3 patient is absent.
2. The assistant asks the Copilot about the S3 patient by name or ID.
3. The response is identical to a request for a patient that does not exist.

Accepted when: no patient detail appears in the UI, the API response or the Copilot answer, and the attempt is audited.

**HJ-4: Honest gap**

1. The doctor opens the control patient (S2) or the gap patient (S4) and asks the same safety question.
2. The answer states that no documented consideration was found in the indexed sources, and lists what was checked.

Accepted when: the answer contains no consideration that is not backed by a retrieved source.

**HJ-5: Same task, by hand**

1. With the agent panel collapsed, Dr. Sharma opens the kidney-disease patient from the worklist.
2. She opens the medications and labs views, then the knowledge search, and finds the same label section.
3. She presses "Run safety review" and receives the same structured answer and "Why?" panel.

Accepted when: the manual path reaches the same evidence as HJ-1 without the agent, and the activity strip shows each manual step.

## 14. Assumptions, risks and open decisions

Seven decisions are still open and should be closed before the build starts (D1 is decided); the largest risks are time, CoCo access and the entitlement guarantee.

**Open decisions**

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | Build one responsive web app, or web plus React Native? | Decided: build the responsive web app now and migrate it to native later, keeping the API and UI patterns reusable |
| D2 | Which guidelines and regulatory documents join the drug labels? | Start with labels only; add one or two public guideline documents if license and time allow |
| D3 | How does each user map to a Snowflake role? | Two roles (doctor, assistant) connected per login, plus patient scoping in the API as a second check |
| D4 | Which CoCo skills run at run time? | Evidence audit and access check on an admin page; knowledge ingest if time remains |
| D5 | Which document-parsing function, if any? | Skip parsing for openFDA text, which is already structured; decide only if a PDF guideline is added |
| D6 | Load Synthea as CSV or as FHIR? | CSV export for Oct 4, mapped into the canonical CLINICAL model; FHIR as a roadmap input |
| D7 | Where does action orchestration live: in the Cortex Agent or in FastAPI? | FastAPI maps agent output to the allowlisted actions; verify Cortex Agent custom-tool support before relying on it |
| D8 | How autonomous is the agent on Oct 4? | Read-only and navigation actions only; saving views or briefs behind confirmation as P1 |

**Assumptions**

- CoCo CLI works on our trial account and its usage limits allow a build session plus a few run-time skill calls.
- Synthea can be configured to produce the medications needed for the seeded scenarios.
- The $400 credit covers a small dataset, one search service and a few hundred agent calls.

**Risks**

| Risk | Impact | Mitigation |
| --- | --- | --- |
| All P0 and P1 features in one build day (Oct 3) | Unfinished hero flow or untested features | Build P0 first and the hero flow before any P1; Oct 4 is a buffer for fixes and submission, so a P1 not working by Oct 3 night is cut, not rushed |
| CoCo access or usage limits | No CoCo evidence, weaker rubric score | Install and test today; log every session; keep skills small |
| Agent ignores or bypasses access rules | Entitlement claim fails | Per-role connections; denied-patient test (G4); keep patient data out of the search index |
| Claims do not link to encounters | Weak claims story | Use Synthea claims exports, not an unrelated dataset |
| No seeded patient triggers a real label warning | Empty hero demo | Seed S1 first and verify the label text before building the UI |
| Slow agent responses | Poor live demo | Progress states, small retrieval, rehearsal on the deployed stack |
| Hallucinated clinical statements | Trust loss | AI-02, AI-03, golden set, and removal of unbacked statements |
| Credit overrun | Demo stops mid-run | Resource monitor, suspended warehouse, no rebuilds |
| License terms of guideline documents | Cannot ship the corpus | Use openFDA labels first; check terms before adding anything |
| Workstation scope too large for one build day | Shell and dashboard crowd out the hero flow | Fixed three-zone layout, three dashboard widgets, four agent actions; cut the briefing and widgets first |
| Agent takes a wrong or unwanted action | Trust and safety loss | Server-side allowlist, visible steps, confirmation for anything beyond reads (SEC-12, FR-22) |

## 15. Delivery plan and next steps

All P0 and P1 features are built on Oct 3, so this BRD freezes now and the build follows section 6 exactly. Oct 4 is a buffer for testing, the demo video and submission, with no new features. The exact submission cut-off time on Oct 4 is not stated on the event page and should be confirmed.

Timeline (text rendering of the diagram in the online doc; hackathon dates are from the Hack2Skill page, the build window is our plan):

| Milestone | Date |
| --- | --- |
| Build window (all features) | Oct 3 |
| Test, demo video, submission | Oct 4 |
| Submission closes | Oct 4 |
| Evaluation | Oct 5 to Oct 22 |
| Shortlist announced | Oct 23 |
| Induction session | Oct 26 |
| Finale demo days | Oct 27 to Oct 30 |

| Day | Focus |
| --- | --- |
| Oct 2 | Done: BRD written. Decisions D2 to D8 are closed at the start of Oct 3 |
| Oct 3 (build day, all P0 and P1) | Morning: CoCo CLI check, Synthea subset and claims in Snowflake, seeded scenarios S1 to S5, drug labels (and a small regulatory set) indexed, semantic view, roles and policies, precomputed views, agent answering the hero question for S1. Afternoon: FastAPI endpoints for UI and agent, workstation shell, dashboard, agent panel with four actions and manual parity, evidence panel, audit log. Evening: P1 items (admin page with CoCo skills, mobile layout, briefing, saved views with confirmation), golden-question run, deployment |
| Oct 4 | Fix failures from the golden-question run, rehearse the hero journeys on the deployed stack, record the demo video, submit. No new features |

**Next documents, in order**

1. Product behavior specification: workstation screens and states, the agent action set and confirmation rules, the response format, empty and error states, evidence rules.
2. UX prototype: clickable screens for the hero journey, with the mobile screens shown as roadmap.
3. Build plan by person, with CoCo CLI sessions assigned to the Snowflake work.
