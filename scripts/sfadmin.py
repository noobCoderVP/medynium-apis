"""Setup-time Snowflake access (personal access token as the admin user). Never imported by the API.

Roles: `bootstrap` uses ACCOUNTADMIN once; everything else uses MED_ADMIN.
"""

import os
import re
from pathlib import Path
from typing import Any

import snowflake.connector
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
KEY_DIR = Path.home() / ".medynium" / "keys"

load_dotenv(ROOT / ".env")


def build_vars() -> dict[str, str]:
    """Template variables available to the numbered SQL files as {{NAME}}."""
    public_key = KEY_DIR / "med_api_svc.pub"
    return {
        "DB": os.environ.get("SNOWFLAKE_DATABASE", "MEDYNIUM"),
        "WH": os.environ.get("SNOWFLAKE_WAREHOUSE", "MEDYNIUM_WH"),
        "ADMIN_USER": os.environ["SNOWFLAKE_ADMIN_USER"],
        "AS_OF": os.environ.get("DEMO_AS_OF_DATE", "2026-10-02"),
        "USD_INR": os.environ.get("USD_INR_RATE", "85"),
        "API_PUBLIC_KEY": public_key.read_text(encoding="utf-8") if public_key.exists() else "",
        "SEARCH_LAG": "30 days",
    }


def connect(role: str, database: str | None = None) -> Any:
    kwargs: dict[str, Any] = {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_ADMIN_USER"],
        "authenticator": "PROGRAMMATIC_ACCESS_TOKEN",
        "token": os.environ["SNOWFLAKE_ADMIN_PAT_TOKEN"],
        "role": role,
    }
    if database:
        kwargs["database"] = database
    return snowflake.connector.connect(**kwargs)


def render(sql: str, variables: dict[str, str]) -> str:
    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            raise KeyError(f"Unknown template variable {{{{{name}}}}}")
        return variables[name]

    return re.sub(r"\{\{([A-Z_]+)\}\}", sub, sql)


def run_script(conn: Any, path: Path, variables: dict[str, str]) -> int:
    """Run every statement in a SQL file; returns the number of statements executed."""
    sql = render(path.read_text(encoding="utf-8"), variables)
    count = 0
    for cursor in conn.execute_string(sql):
        count += 1
        cursor.close()
    return count
