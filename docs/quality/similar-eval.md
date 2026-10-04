# Similar-patient scoring: proxy evaluation

Generated 2026-10-03 23:54 UTC. 66 query patients, top 5 each, candidates 40 per query.

**Read this first.** There is no clinician-labelled ground truth. A neighbour counts as relevant when its broad condition families overlap the query's by at least half (families come from keywords on diagnosis names). This ranks the three scoring modes against that proxy. It is not clinical accuracy and no clinical claim is made from it.

| Scoring mode | Precision at 5 (proxy) |
| --- | --- |
| blend | 0.824 |
| structured | 0.821 |
| embedding | 0.730 |

Weight on embedding similarity in the blend: 0.5.
