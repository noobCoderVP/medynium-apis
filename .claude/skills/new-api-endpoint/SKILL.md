---
name: new-api-endpoint
description: Add or implement an endpoint in medynium-apis inside its feature folder. Use when asked to build, add or fill in an API route, service or repository.
---

1. Pick the feature folder under `src/medynium_api/features/`. Create one (with `__init__.py`, `router.py`, `README.md`) only if none fits, and register it in `src/medynium_api/router.py`.
2. Put request and response models in that feature's `schemas.py` with field descriptions and examples. The UI types are generated from them.
3. Keep the router thin: depend on `CurrentSession`, call `service.py`. The service calls `repository.py`, the only file allowed to import `snowflake`. Use the user's own connection, never a shared role.
4. A denied patient returns the same 404 `not_found` as a missing one. Errors use the codes in `core/errors.py`.
5. Tests in `tests/`: success, 401 without a session, 404 for denied equals missing. Add the route to `PROTECTED` in `tests/test_api_contract.py`.
6. Update the feature `README.md` card.
7. Run `poetry run poe check`, then `poetry run poe openapi`. Tell the user to run `npm run api:types` in `medynium-ui`.
