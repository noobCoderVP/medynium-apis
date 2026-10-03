# KNOWLEDGE schema

Public medical documents, chunked and indexed. **Never contains patient data** (SEC-04), so no row access policy and nothing here can leak a patient. The Cortex Search service reads only this schema. Written at ingestion; never changed at run time (NFR-12).

## Sources

| Source | Content | Tier | How obtained |
| --- | --- | --- | --- |
| **openFDA drug labels** | US FDA prescribing information for 20 to 30 generics | P0 | `api.fda.gov/drug/label.json`, saved as raw JSON under `knowledge/raw/openfda/` |
| **A-Z Medicine Dataset of India** (Kaggle) | Indian brand to generic composition map, prices | P0 (name map only; not indexed as documents) | CSV in `data/india_medicines/` (gitignored; license unconfirmed) |
| **NLEM 2022** | India's essential medicines list, level of care (P, S, T) | P1, flags only | PDF in `knowledge/raw/india/` |
| **ICMR type 2 diabetes guideline, 2018** | Indian treatment guidance | P1, only if the license check passes | PDF in `knowledge/raw/india/` |

Citations must state the source honestly: openFDA text is US FDA labelling, not Indian regulatory text.

## DRUG

One row per in-scope generic. Not patient-keyed.

| Column | Type | Notes |
| --- | --- | --- |
| `DRUG_ID` | VARCHAR PK | `DRG-###` |
| `GENERIC_NAME` | VARCHAR | Lower-case ingredient name, e.g. `metformin`. Single-ingredient generics only for the main corpus. |
| `DISPLAY_NAME` | VARCHAR | e.g. "Metformin hydrochloride". |
| `RXNORM_INGREDIENT` | VARCHAR | Ingredient RxCUI where known. |
| `IN_CORPUS` | BOOLEAN | True when a label is indexed. The gap drug (S4) is a patient medication whose ingredient is not in this table or has `IN_CORPUS = false`. |
| `IN_NLEM` | BOOLEAN | |
| `NLEM_LEVEL` | VARCHAR | `P`, `S`, `T`, or null. P1. |

## DRUG_NAME_MAP

Links names found in patient data and in India to a `DRUG`.

| Column | Type | Notes |
| --- | --- | --- |
| `MAP_ID` | VARCHAR PK | |
| `DRUG_ID` | VARCHAR | FK |
| `NAME_TEXT` | VARCHAR | The alias, lower-case, trimmed. |
| `NAME_KIND` | VARCHAR | `SYNTHEA_INGREDIENT`, `INDIAN_BRAND`, `ALTERNATE_GENERIC`. |
| `SOURCE` | VARCHAR | `SYNTHEA`, `AZ_INDIA`, `MANUAL`. |
| `COMPOSITION_TEXT` | VARCHAR | For Indian brands, the composition string, e.g. `Metformin (500mg)`. |

Rules:

- Indian brands are included only when their composition is a **single** ingredient in scope. Combination brands (e.g. amoxicillin + clavulanic acid) are skipped for the main corpus.
- Synthea medication strings are matched on ingredient substrings, e.g. `24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet` contains `metformin`.
- A medication with no match gets `DRUG_ID = NULL` and appears as "not in the indexed sources" in answers.
- Seeded patients' medicines are chosen from `DRUG` so the demo works.

## DOCUMENT

One row per source document (one label version per drug).

| Column | Type | Notes |
| --- | --- | --- |
| `DOCUMENT_ID` | VARCHAR PK | `DOC-MET-001` style. |
| `DRUG_ID` | VARCHAR | FK, null for general guidelines. |
| `SOURCE` | VARCHAR | `openFDA`, `ICMR`, `NLEM`. |
| `DOC_TYPE` | VARCHAR | `DRUG_LABEL`, `GUIDELINE`, `ESSENTIAL_LIST`. |
| `TITLE` | VARCHAR | e.g. "Metformin hydrochloride tablets: prescribing information". |
| `SOURCE_RECORD_ID` | VARCHAR | openFDA `id` (label record) and `set_id` stored together as JSON in `SOURCE_META`. |
| `VERSION_LABEL` | VARCHAR | openFDA `version` (e.g. `6`) shown as "Label version 6". |
| `EFFECTIVE_DATE` | DATE | openFDA `effective_time` (`YYYYMMDD`). |
| `RETRIEVED_AT` | TIMESTAMP_NTZ | When the raw JSON was fetched. |
| `INGESTED_AT` | TIMESTAMP_NTZ | When it was loaded here. |
| `SOURCE_URL` | VARCHAR | Query URL or file path used. |
| `LICENSE_NOTE` | VARCHAR | e.g. "openFDA: see open.fda.gov/license". |
| `SOURCE_META` | VARIANT | `set_id`, brand and manufacturer names, `rxcui` list. |
| `CONTENT_HASH` | VARCHAR | SHA-256 of the raw text, so reruns are idempotent. |

## DOCUMENT_CHUNK

The unit that is indexed and cited.

| Column | Type | Notes |
| --- | --- | --- |
| `CHUNK_ID` | VARCHAR PK | `CH-####` |
| `DOCUMENT_ID` | VARCHAR | FK |
| `SECTION_KEY` | VARCHAR | openFDA field name: `boxed_warning`, `contraindications`, `warnings_and_cautions`, `dosage_and_administration`, `use_in_specific_populations`, `adverse_reactions`, `drug_interactions`, `pregnancy`, `geriatric_use`. |
| `SECTION_NAME` | VARCHAR | Human heading as shown to users. |
| `CHUNK_INDEX` | NUMBER | Order within a section when a section is split. |
| `TEXT` | VARCHAR | Chunk text. Target 300 to 800 tokens; split on sentence boundaries; never mid-sentence. |
| `PAGE_NO` | NUMBER | Only where the source has pages (PDF guidelines). Null for labels. |
| `TOKEN_COUNT` | NUMBER | |
| `DRUG_ID`, `EFFECTIVE_DATE`, `VERSION_LABEL`, `SOURCE`, `TITLE` | | Denormalised for the search service and to keep citations self-contained. |

Corpus size target: 20 to 30 drugs, 100 to 300 chunks. Chunk by label section so every chunk has a section name.

### Corpus gaps and conflicts (deliberate test data)

| Case | How it is built |
| --- | --- |
| Gap (S4) | A seeded patient is on a drug with no `DRUG` row. |
| Conflict pair (AI-06) | Two documents for the same drug with differing statements and different versions, one clearly labelled as test data. |
| Injection (S5) | In `CLINICAL_NOTE`, not in the corpus, so the corpus stays clean. |

## Ingestion rules

1. Query by `openfda.generic_name` and `product_type = "HUMAN PRESCRIPTION DRUG"`, then **keep only records whose generic name equals the target ingredient**. A plain query can return combination products (for example a search for metformin returned a sitagliptin and metformin label), which must not be mixed in.
2. When several labels qualify, choose the one with the latest `effective_time`, and record its `set_id` and `version`.
3. Save the raw response unchanged before chunking.
4. Skip drugs whose label lacks the sections the demo depends on and pick another drug (plan risk "label has no renal text").
5. Rerunning with the same raw file yields identical ids and hashes.

## Search service

`KNOWLEDGE.LABEL_SEARCH`: Cortex Search over `DOCUMENT_CHUNK.TEXT`, with `SECTION_NAME`, `DRUG_ID`, `SOURCE` and `EFFECTIVE_DATE` as attributes. Built once with a long target lag (NFR-04); rebuilding is avoided to protect credits. Each result carries everything the UI needs for the full citation: document ID, title, source, section, version, effective date, retrieval date, and page number only where one exists.

## Snapshot

The knowledge base is a controlled snapshot, not a live feed. `KNOWLEDGE.SNAPSHOT` holds one row: `SNAPSHOT_DATE`, `DOCUMENT_COUNT`, `CHUNK_COUNT`, `DRUG_COUNT`, `NOTES`. The UI shows the snapshot date wherever evidence appears, and answers say what was indexed, not that they hold the latest information.

## As built (stage 3)

- Corpus: 26 single-ingredient generics, 27 documents (26 openFDA labels and one clearly labelled TEST document for furosemide used for the conflict display), 309 chunks, 100 Indian brand names from the A-Z dataset (single-ingredient only). The NLEM and ICMR PDFs are downloaded but not indexed (P1, licence unchecked).
- `DOCUMENT_CHUNK` gained `SEARCH_TEXT` (what the index embeds: drug, section and text) and `RETRIEVED_DATE` (a citation field).
- Retrieval thresholds, frozen from `knowledge/eval`: unresolved free text must score at least 0.50 cosine similarity; once a drug is named or resolved the search is filtered to it and needs only 0.30. Result on 36 labelled queries: recall@3 1.0, recall@5 1.0, MRR 1.0, negatives 100%.
- The search service is created with `IF NOT EXISTS`; to rebuild it, drop it explicitly (credit protection).
