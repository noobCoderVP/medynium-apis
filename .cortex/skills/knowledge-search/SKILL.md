---
name: knowledge-search
description: Search and analyse the Medynium drug-label corpus with Cortex Search and check coverage. Use to answer what the labels say or whether a drug is indexed.
---

1. Search through the service: `GET /knowledge/search?q=<drug or brand>`; the Cortex Search service is `KNOWLEDGE.LABEL_SEARCH`.
2. Coverage: `GET /admin/knowledge/coverage` lists drugs with no indexed label. A drug with no label is answered "no label indexed", never from another drug's text.
3. To add a drug, an admin runs `knowledge/ingest/fetch_openfda.py` then `extend.py` (insert-only), then `knowledge/eval/run_eval.py`; mark the request ADDED.
4. Cite title, section, version and dates for every statement.
