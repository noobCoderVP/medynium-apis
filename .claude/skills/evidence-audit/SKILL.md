---
name: evidence-audit
description: Audit that every AI answer statement is backed by evidence and that negation, family-history, refusal, gap and injection cases still behave (AI-01 to AI-13). Use after any change to prompts, the validator, routing or the golden sets.
---

1. Run `poetry run pytest tests/test_negation_guard.py tests/test_allergy_rule.py tests/test_findings.py` (offline guards).
2. Run `poetry run poe eval:all` and read `docs/quality/golden-report.md` and `injection-report.md`; report every failed case id with its reason.
3. Confirm these groups each have at least one passing case: hero, honest-gap, access, refusal, negation (G23 to G25), injection.
4. Every failed `evidence_backed` or `not_contains` case is a bug in the prompt or validator, not in the case. Fix the cause; do not loosen the expectation.
5. If a prompt file changed, confirm the prompt version hash changed in the audit row, then re-run `poetry run poe eval:routing`.
6. Summarise in `docs/quality/coco-runs.md`: date, command, pass count, anything the audit caught.
