"""Health probes under the service role. A suspended warehouse is normal, not a failure."""

from medynium_api.core.snowflake.queries import Row, fetch_one
from medynium_api.core.snowflake.role_session import service_cursor


class HealthRepository:
    def probe(self, warehouse: str) -> tuple[Row | None, Row | None]:
        with service_cursor() as cur:
            ident = fetch_one(cur, "SELECT CURRENT_ROLE() AS ROLE_NAME, CURRENT_WAREHOUSE() AS WH")
            cur.execute("SHOW WAREHOUSES LIKE %s", (warehouse,))
            row = cur.fetchone()
            state = {"state": row.get("state")} if row else None
        return ident, state

    def audit_table_writable(self) -> bool:
        with service_cursor() as cur:
            return fetch_one(cur, "SELECT COUNT(*) AS N FROM SECURITY.AUTH_EVENT") is not None
