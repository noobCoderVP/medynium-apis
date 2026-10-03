# Dashboard and patient endpoints

Conventions: [README.md](README.md). All endpoints need a session. For **any** `{patient_id}` the caller is not entitled to, or that does not exist, the response is `404 not_found` with the same body and similar latency. No AI is called by any endpoint on this page; data comes from precomputed tables ([../database/analytics.md](../database/analytics.md)).

## `GET /dashboard`

Three widgets from precomputed views, scoped by the row access policy to the caller's patients (FR-17).

```json
{
  "as_of": "2026-10-02",
  "worklist": [
    {
      "patient_id": "P-1042",
      "name": "Rahul Patel",
      "age": 58,
      "sex": "M",
      "last_encounter": { "date": "2026-10-02", "kind": "EMERGENCY", "label": "Emergency visit" },
      "flags": [
        { "type": "NEW_LAB", "label": "2 new labs" },
        { "type": "RECENT_EMERGENCY", "label": "ED visit yesterday" }
      ]
    }
  ],
  "recent_changes": {
    "labs": [
      { "patient_id": "P-1042", "name": "Rahul Patel", "test": "eGFR", "latest": 42, "previous": 47, "unit": "mL/min/1.73 m²", "date": "2026-09-18", "abnormal": "LOW" }
    ],
    "medications": [
      { "patient_id": "P-1042", "name": "Rahul Patel", "drug": "Metformin", "change": "Dose raised from 500 mg on 14 Aug 2026", "date": "2026-08-14" }
    ]
  },
  "utilization": {
    "window": "last_12_months",
    "opd_visits": 56, "emergency_visits": 6, "hospitalizations": 5, "procedures": 24,
    "approved": { "amount": 590000.00, "currency": "INR" }
  }
}
```

`worklist` is limited to 10 patients, **ranked before the cut**: a recent emergency visit outranks everything, then new labs, then a medicine change, then a new document; ties go to more flags, then the most recent change (`core/ranking.py`). `GET /patients` with `sort=flags` uses the same order, and lists everyone.

## `GET /patients`

Query: `q` (name or id substring), `changed` (`true` returns only flagged patients), `limit`, `offset`. Standard list shape. Item:

```json
{
  "patient_id": "P-1042",
  "name": "Rahul Patel",
  "age": 58,
  "sex": "M",
  "main_diagnoses": ["Type 2 diabetes mellitus", "Chronic kidney disease, stage 3b"],
  "last_encounter": { "date": "2026-10-02", "kind": "EMERGENCY", "label": "Emergency visit" },
  "flags": [{ "type": "NEW_LAB", "label": "2 new labs" }]
}
```

Powers the worklist page and the top-bar patient search. Sorted by most recent encounter unless `q` is given.

## `GET /patients/{patient_id}`

The Patient 360 overview (FR-02). Each value carries its date and source table. Opening a patient writes a `VIEW_PATIENT` audit row. `allergies` lists active allergies, most severe first; an empty list means none are recorded, not none known.

```json
{
  "patient_id": "P-1042",
  "name": "Rahul Patel",
  "age": 58,
  "sex": "M",
  "city": "Ahmedabad",
  "as_of": "2026-10-02",
  "allergies": [
    { "allergy_id": "ALG-1001", "substance": "Sulfonamide antibiotics", "reaction": "Rash", "severity": "MODERATE" }
  ],
  "diagnoses": [
    { "diagnosis_id": "DX-3355", "description": "Chronic kidney disease, stage 3b", "onset_year": 2025, "source": "CLINICAL.DIAGNOSIS" }
  ],
  "medications": [
    { "medication_id": "RX-88231", "drug": "Metformin", "dose": "1000 mg twice daily", "started": "2019-03-12", "change": "Dose raised from 500 mg on 14 Aug 2026", "in_knowledge_base": true, "source": "CLINICAL.MEDICATION" }
  ],
  "latest_labs": [
    { "lab_id": "LAB-77120", "test": "eGFR", "code": "33914-3", "value": 42, "unit": "mL/min/1.73 m²", "date": "2026-09-18", "previous": { "value": 47, "date": "2026-06-08" }, "ref": { "low": 60, "high": null }, "flag": "LOW", "source": "CLINICAL.LAB_RESULT" }
  ],
  "recent_events": [
    { "event_id": "EV-1", "date": "2026-10-02", "type": "ENCOUNTER", "title": "Emergency visit", "summary": "Chest discomfort. ECG and blood tests done." }
  ],
  "utilization": {
    "window": "last_12_months", "opd_visits": 12, "emergency_visits": 1, "hospitalizations": 2, "procedures": 8,
    "approved": { "amount": 240000.00, "currency": "INR" }
  },
  "agent_scope_label": "Agent scope: this patient"
}
```

## `GET /patients/{patient_id}/medications`

Query: `status` (`active` default, `all`). Items: `medication_id`, `drug`, `description`, `dose`, `strength`, `started`, `stopped`, `last_change_date`, `change_note`, `in_knowledge_base`, `also_sold_as` (Indian brand names from the drug map, optional).

## `GET /patients/{patient_id}/labs`

Latest and previous value per test, with reference range and flag, as in `latest_labs` above. Query: `q` (test name).

## `GET /patients/{patient_id}/labs/{code}/trend`

`code` is a LOINC code or a short alias (`eGFR`, `HbA1c`).

```json
{
  "test": "eGFR", "code": "33914-3", "unit": "mL/min/1.73 m²",
  "ref": { "low": 60, "high": null },
  "points": [
    { "lab_id": "LAB-70211", "date": "2025-11-04", "value": 58 },
    { "lab_id": "LAB-72040", "date": "2026-02-12", "value": 52 },
    { "lab_id": "LAB-75012", "date": "2026-06-08", "value": 47 },
    { "lab_id": "LAB-77120", "date": "2026-09-18", "value": 42 }
  ]
}
```

`404 not_found` if the patient is missing or denied. A patient who exists but has no results for the code returns `200` with `points: []`. An unknown code returns `400 invalid_request`.

## `GET /patients/{patient_id}/timeline`

Query: `from`, `to` (dates, inclusive), `types` (comma list of event types). Returns newest first:

```json
{
  "items": [
    {
      "event_id": "EV-204",
      "date": "2026-10-02",
      "type": "CLAIM",
      "title": "Claim approved",
      "summary": "CLM-1024, ₹18,400, linked to ENC-20931",
      "record": { "table": "CLINICAL.CLAIM", "id": "CLM-1024" },
      "encounter_id": "ENC-20931"
    }
  ],
  "total": 8
}
```

Event types: `ENCOUNTER`, `DIAGNOSIS`, `MEDICATION_START`, `MEDICATION_CHANGE`, `LAB_PANEL`, `CLAIM`, `NOTE`. Selecting an event fetches its record through the endpoint for that type (medications, labs, claims, notes).

## `GET /patients/{patient_id}/claims`

Counts, approved amounts and claims linked to encounters (FR-04).

```json
{
  "utilization": {
    "window": "last_12_months", "opd_visits": 12, "emergency_visits": 1, "hospitalizations": 2, "procedures": 8,
    "billed": { "amount": 260000.00, "currency": "INR" },
    "approved": { "amount": 240000.00, "currency": "INR" }
  },
  "claims": [
    {
      "claim_id": "CLM-1024", "encounter_id": "ENC-20931", "service_date": "2026-10-02",
      "service": "Emergency visit, ECG, blood tests", "status": "APPROVED",
      "billed": { "amount": 19000.00, "currency": "INR" },
      "approved": { "amount": 18400.00, "currency": "INR" }
    }
  ]
}
```

Totals equal the SQL ground-truth query (tested).

## `GET /patients/{patient_id}/notes`, `GET /patients/{patient_id}/notes/{note_id}`

List items: `note_id`, `title`, `type`, `date`, `encounter_id`. Detail adds `author` and `body` (plain text, rendered as text only, never as HTML). A note that contains instruction-like text is returned as is; it is treated as data by the agent (AI-05).

## Pins

Pinned evidence shown on the patient workspace. Created by the user's pin icon or by the `pin_evidence` agent action.

### `GET /patients/{patient_id}/pins`

```json
{ "items": [ { "pin_id": "PIN-12", "answer_id": "ANS-0004", "evidence_id": "S1", "label": "Metformin label: renal impairment, Label version 6", "created_at": "2026-10-03T08:50:00Z" } ] }
```

### `POST /patients/{patient_id}/pins`

```json
{ "answer_id": "ANS-0004", "evidence_id": "S1", "note": "check at next visit" }
```

`201` with the pin. `404 not_found` if the answer does not belong to the caller and patient. Audited.

### `DELETE /patients/{patient_id}/pins/{pin_id}`

`204`. Users can delete only their own pins.

## Findings

A clinician's decision on a statement from a safety review. Only a signed-in user raises or changes one; the agent cannot. Findings are shared by everyone entitled to the patient. Every raise and decision is audited (`RAISE_FINDING`, `DECIDE_FINDING`). Denied and missing patients and findings return the standard `404`.

### `GET /patients/{patient_id}/findings`

```json
{
  "open_count": 1,
  "items": [
    {
      "finding_id": "FND-3A9C0D12", "patient_id": "P-1042", "answer_id": "ANS-0004", "consideration_id": "C3",
      "summary": "A low eGFR with metformin may warrant clinician review.",
      "status": "NEW", "reason": null, "follow_up_on": null, "assigned_to": null, "assigned_to_name": null,
      "created_by_name": "Dr. Sharma", "created_at": "2026-10-03T09:10:00Z", "updated_at": null
    }
  ]
}
```

Open means `NEW`, `FLAGGED` or `ESCALATED`; open findings come first.

### `POST /patients/{patient_id}/findings`

`{ "answer_id": "ANS-0004", "consideration_id": "C3" }` creates a `NEW` finding from a statement in one of the caller's own answers about this patient (the text is copied server-side, never taken from the request). `201` with the finding. Repeating the same request returns the same finding. `404` if the answer is not the caller's, is about another patient, or has no such statement.

### `PATCH /findings/{finding_id}`

`{ "status": "...", "reason": "...", "follow_up_on": "2026-10-10", "assigned_to": "<user id>" }`. Rules: `DISMISSED` needs a `reason`; `FLAGGED` needs a `follow_up_on` of today or later; `ESCALATED` needs an `assigned_to` who currently has this patient and is not the caller; the status must change (except re-flagging with a new date). `NEW` re-opens. Violations return `422 invalid_request` with a `details` list.

### `GET /patients/{patient_id}/colleagues`

Other active users who currently have this patient: `{ "items": [{ "user_id", "name", "role" }] }`. The choices for an escalation.
