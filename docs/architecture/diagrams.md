# Diagram gallery

Every diagram here is Mermaid, so GitHub renders it in place. The core system diagrams (context, layers, routing, safety review, ER) also appear in the [README](../../README.md), [overview](overview.md) and [database docs](../database/README.md); this page adds the ones that show behaviour over time and under failure.

| # | Diagram | Type | Answers |
| --- | --- | --- | --- |
| 1 | [Workspace map](#1-workspace-map) | flowchart | How the three repos connect |
| 2 | [Containers and trust boundaries](#2-containers-and-trust-boundaries) | flowchart | What runs where, and what is trusted |
| 3 | [Sign-in, refresh and reuse detection](#3-sign-in-refresh-and-reuse-detection) | sequence | How sessions are issued and revoked |
| 4 | [One request under the user's role](#4-one-request-under-the-users-role) | sequence | How a role reaches Snowflake |
| 5 | [Assistant answer, end to end](#5-assistant-answer-end-to-end) | sequence | Router, handler, validator, audit |
| 6 | [A proposal and its approval](#6-a-proposal-and-its-approval) | sequence | Why the assistant cannot write |
| 7 | [Report intake](#7-report-intake) | sequence | Paper to approved rows |
| 8 | [Finding lifecycle](#8-finding-lifecycle) | state | What a clinician's decision allows |
| 9 | [Report and row lifecycle](#9-report-and-row-lifecycle) | state | Statuses of a report and its rows |
| 10 | [Record write path](#10-record-write-path) | flowchart | Double entitlement check, versioning |
| 11 | [Data ingestion and build order](#11-data-ingestion-and-build-order) | flowchart | How data and labels get into Snowflake |
| 12 | [Schemas and roles](#12-schemas-and-roles) | flowchart | Which role touches which schema |
| 13 | [Findings, reports and history (ER)](#13-findings-reports-and-history-er) | ER | The newer tables |
| 14 | [Evidence chain](#14-evidence-chain) | flowchart | From a statement to its source |
| 15 | [Statement validation](#15-statement-validation) | flowchart | When a statement is dropped |
| 16 | [Delivery pipeline](#16-delivery-pipeline) | flowchart | CI, deploy, types |
| 17 | [Mobile session and lock](#17-mobile-session-and-lock) | state | App lifecycle |
| 18 | [How the repos were built](#18-how-the-repos-were-built) | timeline | Order of work |

## 1. Workspace map

```mermaid
flowchart LR
  subgraph WS [medynium workspace]
    API[medynium-apis<br/>FastAPI, SQL, evals]
    UI[medynium-ui<br/>Next.js workstation]
    APP[medynium-app<br/>Expo mobile]
    DOCS[requirements<br/>BRD, SRS, plan]
  end
  DOCS -. defines .-> API
  API -->|openapi.json| UI
  API -->|openapi.json| APP
  UI -->|/api proxy| API
  APP -->|HTTPS, bearer| API
  API --> SF[(Snowflake)]
```

## 2. Containers and trust boundaries

```mermaid
flowchart TB
  subgraph Untrusted [Untrusted]
    Browser[Browser]
    Phone[Phone]
    Text[Text in notes, labels, reports]
  end
  subgraph Edge [Vercel]
    Next[Next.js + /api proxy]
  end
  subgraph Run [Google Cloud Run]
    Fast[FastAPI<br/>auth, access, router, handlers, validator, audit]
  end
  subgraph SFB [Snowflake: system of record and the real boundary]
    RAP[Row access policies]
    Roles[One role per user]
    Cortex[Cortex Analyst, Search, Agent]
    Data[(SECURITY, CLINICAL, KNOWLEDGE, ANALYTICS)]
  end
  Browser --> Next --> Fast
  Phone --> Fast
  Text -. data, never instructions .-> Fast
  Fast -->|key-pair, then USE ROLE| Roles --> RAP --> Data
  Fast --> Cortex --> Data
```

The UI and the router are not boundaries. The boundary is the database role plus the server checks that run on every route.

## 3. Sign-in, refresh and reuse detection

```mermaid
sequenceDiagram
  participant B as Browser or app
  participant A as API
  participant S as SECURITY schema
  B->>A: POST /auth/login (email, password)
  A->>S: Verify Argon2id hash, check lockout
  alt wrong, disabled or locked
    A-->>B: 401 (same message for all three)
  else valid
    A->>S: Create AUTH_SESSION, log AUTH_EVENT
    A-->>B: Access and refresh tokens (httpOnly cookies, or bearer for mobile)
  end
  Note over B,A: Later, the access token expires
  B->>A: POST /auth/refresh (refresh token)
  A->>S: Rotate refresh token
  A-->>B: New pair
  B->>A: POST /auth/refresh (the OLD token again)
  A->>S: Reuse detected, revoke the whole session
  A-->>B: 401
```

Five failed sign-ins lock the account for 15 minutes.

## 4. One request under the user's role

```mermaid
sequenceDiagram
  participant C as Client
  participant R as Router (thin)
  participant Sv as Service
  participant Re as Repository
  participant S as Snowflake
  C->>R: GET /patients/P-1042 (token)
  R->>R: Verify token, resolve user and role
  R->>Sv: patient_id, caller
  Sv->>Re: read overview
  Re->>S: Connect with the service key-pair
  Re->>S: USE ROLE U_caller
  Re->>S: SELECT ... FROM ANALYTICS.PATIENT_360
  S-->>Re: rows the role may see (maybe none)
  Re-->>Sv: rows
  Sv-->>R: model or NotFound
  R-->>C: 200, or 404 identical for denied and missing
```

## 5. Assistant answer, end to end

```mermaid
sequenceDiagram
  participant U as Doctor
  participant API as POST /copilot/ask (SSE)
  participant RT as Router model
  participant H as Route handler
  participant V as Validator
  participant AU as Audit writer
  participant SF as Snowflake under U's role
  U->>API: question, screen, patient id
  API->>API: Entitlement check first
  API->>RT: question, screen, patient id only
  RT-->>API: route, action, confidence
  API->>H: dispatch
  H->>SF: fixed SQL, Analyst, Search or Agent
  H-->>U: SSE step events
  H->>V: draft statements and evidence
  V->>V: allowlist, entitlement, evidence match
  V-->>API: kept statements, dropped statements
  API->>AU: one row: route, model, steps, outcome, prompt hash
  API-->>U: tagged statements, answer id
```

## 6. A proposal and its approval

```mermaid
sequenceDiagram
  actor D as Doctor
  participant AS as Assistant
  participant P as Proposals store
  participant UI as Preview card
  participant RW as Records service
  participant SF as Snowflake
  D->>AS: "Add an allergy to penicillin"
  AS->>AS: Validate arguments, free text must come from the question
  AS->>P: Save proposal (owner = D, expires after 15 minutes)
  AS-->>UI: Preview of exactly what would be written
  alt Doctor approves
    D->>UI: Approve
    UI->>RW: Approve proposal (only its owner)
    RW->>SF: INTAKE.WRITE_RECORD, entitlement re-checked inside
    RW-->>D: Written, versioned, history row added
  else Doctor discards
    D->>UI: Discard
    UI->>P: Mark discarded, nothing written
  end
```

## 7. Report intake

```mermaid
sequenceDiagram
  actor U as Doctor or assistant
  participant API as Reports API
  participant ST as Private encrypted stage
  participant PD as PARSE_DOCUMENT
  participant LM as Reading model
  participant EX as extraction.py
  participant SF as CLINICAL.REPORT
  U->>API: POST report (PDF, PNG or JPEG)
  API->>API: Entitlement, type from bytes, size and rate caps
  API->>ST: Store file
  API-->>U: Accepted, status UPLOADED
  API->>PD: Read pages (background)
  PD-->>API: Page text
  API->>LM: Page text to fixed JSON rows
  LM-->>API: Candidate rows
  API->>EX: Keep a row only if its quote is on the page and its number is in the quote
  EX-->>SF: Rows with quote, page, code-set confidence
  Note over API,SF: Status EXTRACTED, name compared with the patient
  U->>API: Accept, edit or reject each row
  U->>API: Approve the report (doctor only)
  API->>SF: Write accepted rows to the record, source = this report
```

## 8. Finding lifecycle

```mermaid
stateDiagram-v2
  [*] --> NEW: A person raises it from a safety statement
  NEW --> ACKNOWLEDGED: Acknowledge
  NEW --> FLAGGED: Follow up (date today or later required)
  NEW --> ESCALATED: Escalate (a colleague who has the patient)
  NEW --> DISMISSED: Dismiss (a reason is required)
  FLAGGED --> FLAGGED: Re-date the follow-up
  FLAGGED --> ACKNOWLEDGED
  FLAGGED --> ESCALATED
  FLAGGED --> DISMISSED
  ESCALATED --> ACKNOWLEDGED
  ESCALATED --> DISMISSED
  note right of NEW
    Open states: NEW, FLAGGED, ESCALATED.
    They appear on the Pending page.
  end note
```

The rules live in `features/findings/rules.py`, as pure functions tested without a database. The diagram shows the usual paths. The code refuses a decision that is incomplete (no reason, no future date, no valid colleague) and a repeat of the same state, except re-dating a follow-up; it does not otherwise restrict which state follows which.

## 9. Report and row lifecycle

```mermaid
stateDiagram-v2
  state "Report" as RP {
    [*] --> UPLOADED
    UPLOADED --> PARSING
    PARSING --> EXTRACTED
    PARSING --> FAILED: a sweeper retries a stuck report up to 3 times
    EXTRACTED --> REVIEWED: Doctor approves
    EXTRACTED --> REJECTED: Doctor rejects
  }
  state "Each extracted row" as RW {
    [*] --> PENDING
    PENDING --> ACCEPTED
    PENDING --> EDITED
    PENDING --> REJECTED_ROW
    ACCEPTED --> APPROVED: report approved
    EDITED --> APPROVED: report approved
    REJECTED_ROW --> PENDING: reset
    ACCEPTED --> PENDING: reset
  }
```

`REJECTED_ROW` stands for the row status `REJECTED`, renamed here so it does not clash with the report status.

## 10. Record write path

```mermaid
flowchart TD
  W[Doctor edits a record] --> A{Doctor role?}
  A -->|assistant| F403[403 forbidden]
  A -->|doctor| E{Entitled in the API?}
  E -->|no| N404[404, audited like a missing patient]
  E -->|yes| K{Idempotency-Key seen?}
  K -->|yes| RET[Return the first result]
  K -->|no| V{Version matches the one read?}
  V -->|stale| C409[409 conflict]
  V -->|current| P[CALL INTAKE.WRITE_RECORD as the writer role]
  P --> E2{Entitled inside Snowflake?}
  E2 -->|no| N404
  E2 -->|yes| H[Insert-only history row, new version]
  H --> RB[Rebuild that patient's read models]
  RB --> OK[Return, worklist and assistant already show it]
```

## 11. Data ingestion and build order

```mermaid
flowchart LR
  subgraph Sources [Read at ingestion only, by a person]
    SY[Synthea CSV]
    OF[openFDA labels: 68 files]
    IN[A-Z India medicines, NLEM 2022, ICMR T2DM 2018]
    SC[Hand-seeded scenarios S1 to S5]
  end
  SY --> L[load_raw.py] --> RAW[(RAW)]
  SC --> SD[seed_scenarios.py] --> RAW
  RAW --> T[20_transform_clinical.sql] --> CL[(CLINICAL)]
  OF --> IG[knowledge/ingest] --> KN[(KNOWLEDGE chunks)]
  IN --> IG
  KN --> SS[50_search_service.sql<br/>Cortex Search]
  CL --> B[30_build_analytics.sql] --> AN[(ANALYTICS read models)]
  CL --> EM[31_build_embeddings.sql] --> AN
  AN --> SV[40_semantic_view.sql<br/>Cortex Analyst]
  AN & KN & CL --> POL[06_policies.sql<br/>row access policies] --> CHK[90_checks.sql<br/>17 checks]
```

All steps are idempotent and can be re-run on a clean or populated schema.

## 12. Schemas and roles

```mermaid
flowchart LR
  ADM[MED_ADMIN<br/>setup, by a person] -->|create, load| ALL[(All schemas)]
  SVC[MED_API service<br/>key-pair] -->|read, insert auth events| SEC[(SECURITY)]
  SVC -->|USE ROLE| U[U_user roles]
  U -->|inherit| BASE[MED_DOCTOR or MED_ASSISTANT]
  BASE -->|read| CL[(CLINICAL)]
  BASE -->|read| KN[(KNOWLEDGE)]
  BASE -->|read, insert audit and answers| AN[(ANALYTICS)]
  WR[MED_CLINICAL_WRITER<br/>owns write procedures] -->|insert, update| CL
  SVC -->|CALL procedures| WR
```

The runtime service identity has no privilege on patient tables. The writer role is reached only through procedures that re-check entitlement.

## 13. Findings, reports and history (ER)

The core ER diagram is in the [database README](../database/README.md#entity-relationships). This one adds the newer tables.

```mermaid
erDiagram
  PATIENT ||--o{ REPORT : "uploaded to"
  REPORT ||--o{ REPORT_ROW : extracts
  REPORT_ROW }o--o| LAB_RESULT : "approved into"
  REPORT_ROW }o--o| MEDICATION : "approved into"
  REPORT_ROW }o--o| DIAGNOSIS : "approved into"
  ANSWER ||--o{ FINDING : "raised from"
  PATIENT ||--o{ FINDING : about
  APP_USER ||--o{ FINDING : "decides or is assigned"
  PATIENT ||--o{ RECORD_HISTORY : "insert-only versions"
  APP_USER ||--o{ RECORD_HISTORY : "written by"
  PATIENT ||--o{ PIN : has
  ANSWER ||--o{ PIN : "pinned from"
  APP_USER ||--o{ SAVED_VIEW : owns
  PATIENT ||--o| PATIENT_EMBEDDING : "similarity vector"
```

Table names in this diagram are logical. Exact names and columns are in the [data dictionary](../database/data-dictionary.md).

## 14. Evidence chain

```mermaid
flowchart LR
  S[Statement shown to the doctor] --> T{Tag}
  T -->|patient fact| PF[Patient records: ids and dates]
  T -->|retrieved source| SRC[Label chunk: title, section, version, dates]
  T -->|AI synthesis| BOTH[Must cite both a record and a source]
  PF --> SQL[The SQL that ran]
  SRC --> DOC[Document in KNOWLEDGE]
  BOTH --> PF
  BOTH --> SRC
  SQL & DOC --> W[Why? panel, shareable link]
  W --> PIN[Pin to the patient workspace]
```

## 15. Statement validation

```mermaid
flowchart TD
  D[Draft statement] --> Q1{Cites evidence?}
  Q1 -->|no| X[Drop]
  Q1 -->|yes| Q2{Evidence type matches the tag?}
  Q2 -->|no| X
  Q2 -->|yes| Q3{Evidence belongs to this patient and this user's access?}
  Q3 -->|no| X
  Q3 -->|yes| Q4{Negation or allergy rule contradicts it?}
  Q4 -->|yes| X
  Q4 -->|no| K[Keep, tag and store with evidence]
  K --> G{Any statements left?}
  G -->|none| H[Say: nothing found in the indexed sources. Never: no risk]
  G -->|some| O[Show them]
```

## 16. Delivery pipeline

```mermaid
flowchart LR
  DEV[Developer] -->|poe check, npm run check| PC[pre-commit and Husky]
  PC --> GH[GitHub push or PR]
  GH --> CI1[API job: ruff, format, mypy strict, pytest]
  CI1 --> CI2[OpenAPI file must be fresh<br/>git diff --exit-code]
  GH --> CI3[Docker image builds]
  CI2 & CI3 --> OK{Green?}
  OK -->|yes| DEP[scripts/deploy.py<br/>Cloud Build, Cloud Run]
  OK -->|no| FIX[Fix, never skip]
  API[API schemas] -->|poe openapi| OA[openapi.json]
  OA -->|npm run api:types| UI[UI and app types]
  DEP --> VER[Vercel UI points BACKEND_URL at Cloud Run]
```

## 17. Mobile session and lock

```mermaid
stateDiagram-v2
  [*] --> SignedOut
  SignedOut --> SignedIn: Password, or invite link
  SignedIn --> Locked: 60 seconds away from the app
  Locked --> SignedIn: Fingerprint, face or screen-lock unlock
  SignedIn --> SignedOut: 5 minutes away on a phone with no screen lock
  SignedIn --> SignedOut: Sign out (tokens and cache cleared)
  SignedIn --> SignedOut: Refresh token reused, revoked or expired
  SignedIn --> SignedIn: Refresh rotates tokens in the secure store
```

The lock is a local convenience on top of the server session, not a replacement for it. Tokens live in the secure store only. The query cache is memory-only and cleared on sign-out, and Android backups are disabled.

## 18. How the repos were built

```mermaid
timeline
  title Build order (implementation plan slices)
  section Foundation
    Slice 0 to 2 : Verify the platform
                 : Foundation, data and seeded patients
                 : Entitlement gate, the AI-layer test
  section Core product
    Slice 3 to 5 : Patient 360 and dashboard, no AI
                 : Knowledge base and search
                 : Hero safety review with evidence
  section Assistant and trust
    Slice 6 to 9 : Agent routing and the copilot
                 : Agent actions and manual parity
                 : Audit and activity log
                 : Quality evidence
  section Ship
    Slice 10 to 12 : P1 items
                   : Deploy and rehearse
                   : Record and submit
  section Production pass
    After the plan : Record write path and report intake
                   : Panel agent, proposals, drug route
                   : Similar patients, mobile app, drug coverage
```

The slices are from the implementation plan; the last section is the later production pass. The authoritative order and done-when checks are in the [implementation plan](../requirements/Medynium_Implementation_Plan.md).
