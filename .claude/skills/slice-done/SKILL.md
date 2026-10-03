---
name: slice-done
description: Verify a finished slice in medynium-apis against its done-when check and tick the tracker. Use when a slice or feature is finished.
---

1. Read the slice in `../Medynium_Implementation_Plan.md` and restate its done-when check.
2. Run `poetry run poe check` and `poetry run poe openapi`; report any failure verbatim.
3. Confirm each new route has 401 and denied-equals-missing tests, and that the feature README card is current.
4. Confirm the hard rules in AGENTS.md still hold (entitlement first, user role, closed actions, evidence or nothing).
5. Tick the tracker in section 8 of the plan only if every item passes; otherwise list what is left.
