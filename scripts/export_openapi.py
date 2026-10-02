"""Write the OpenAPI schema to docs/api/openapi.json. The UI generates its types from this file."""

import json
from pathlib import Path

from medynium_api.main import app

out = Path(__file__).resolve().parent.parent / "docs" / "api" / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
print(f"Wrote {out}")
