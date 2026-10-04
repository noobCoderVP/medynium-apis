# Medynium documentation

Architecture, data, API and quality documentation for the Medynium backend. Source documents: [BRD](requirements/Medynium_BRD.md), [SRS](requirements/Medynium_SRS.md) and [implementation plan](requirements/Medynium_Implementation_Plan.md), plus the decisions recorded here.

## Read in this order

1. [Architecture overview](architecture/overview.md): components, flows, trust boundaries, deployment, risks
2. [Security and access model](architecture/security-and-access.md): real accounts, sessions, roles, row access, what must be validated first
3. [AI layer](architecture/ai-layer.md): routing, safety review, answer and evidence objects
4. [Decision log](architecture/decisions.md): what was decided, what is proposed, what changed from the SRS, open questions
5. [Database](database/README.md): schemas and tables, loading and India localisation, seeded scenarios
6. [API reference](api/README.md): conventions, errors, SSE, then each endpoint group
7. [External dependencies](external-dependencies.md): accounts, keys and decisions needed from outside the code

## Status markers

Each document marks items as **Accepted**, **Proposed** or **To validate**. The ones that need your answer are in [decisions.md](architecture/decisions.md#open-questions). The one that can change the design is **ADR-003** (a Snowflake role per app user), which is settled by the Slice 2 spike, not by discussion.

## Keeping docs and code in step

- `docs/api/openapi.json` is generated from the code (`poetry run poe openapi`) and checked in CI.
- When a table or endpoint changes, update its document in the same change.
- Anything that departs from the SRS goes in the "Changes to the SRS" table in the decision log.
