---
name: evidence-audit
description: Audit stored Medynium answers for evidence-or-nothing. Use to check that every statement cites patient evidence or a source chunk.
---

1. As the admin's own role, read `ANALYTICS.COPILOT_AUDIT` and the stored answers for a sample of recent answers.
2. For each statement check: tag matches evidence (patient_fact needs a P id, retrieved_source an S id, ai_synthesis both).
3. Flag any statement without evidence, any "no risk" wording, and any answer whose sources lack title, section, version or dates.
4. Report counts and the ids of offenders. Do not modify stored answers.
