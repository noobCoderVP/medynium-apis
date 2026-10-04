"""Drug requests (service role, SECURITY.DRUG_REQUEST: no patient data) and the coverage figures (the caller's own role:
the corpus is public, and the medicine counts are limited by the entitled-patient policy to the caller's own patients)."""

from dataclasses import dataclass

from medynium_api.core.ids import new_id
from medynium_api.core.snowflake.queries import Row, execute, fetch_all, fetch_one
from medynium_api.core.snowflake.role_session import service_cursor, user_cursor

COLUMNS = "REQUEST_ID, DRUG_TEXT, NOTE, REQUESTED_BY, REQUESTED_AT, STATUS, DECIDED_BY, DECIDED_AT, DECISION_NOTE"


@dataclass
class CoverageData:
    head: Row
    gaps: list[str]
    snapshot: Row
    unlabelled: list[Row]
    open_requests: int


class DrugCoverageRepository:
    def open_request(self, user_id: str, drug: str) -> Row | None:
        with service_cursor() as cur:
            return fetch_one(
                cur,
                f"SELECT {COLUMNS} FROM SECURITY.DRUG_REQUEST WHERE REQUESTED_BY = %s AND STATUS = 'OPEN' "
                "AND LOWER(DRUG_TEXT) = LOWER(%s)",
                (user_id, drug),
            )

    def create_request(self, user_id: str, drug: str, note: str | None) -> Row:
        request_id = new_id("DRQ", 8)
        with service_cursor() as cur:
            execute(
                cur,
                "INSERT INTO SECURITY.DRUG_REQUEST (REQUEST_ID, DRUG_TEXT, NOTE, REQUESTED_BY, REQUESTED_AT, STATUS) "
                "SELECT %s, %s, %s, %s, SYSDATE(), 'OPEN'",
                (request_id, drug, note, user_id),
            )
            row = fetch_one(
                cur,
                f"SELECT {COLUMNS} FROM SECURITY.DRUG_REQUEST WHERE REQUEST_ID = %s",
                (request_id,),
            )
        assert row is not None
        return row

    def requests(self, status: str | None, user_id: str | None) -> list[Row]:
        where, params = ["TRUE"], []
        if status:
            where.append("STATUS = %s")
            params.append(status)
        if user_id:
            where.append("REQUESTED_BY = %s")
            params.append(user_id)
        with service_cursor() as cur:
            return fetch_all(
                cur,
                f"SELECT {COLUMNS} FROM SECURITY.DRUG_REQUEST WHERE {' AND '.join(where)} "
                "ORDER BY IFF(STATUS = 'OPEN', 0, 1), REQUESTED_AT DESC LIMIT 200",
                params,
            )

    def decide(self, request_id: str, status: str, note: str | None, actor_id: str) -> int:
        with service_cursor() as cur:
            return execute(
                cur,
                "UPDATE SECURITY.DRUG_REQUEST SET STATUS = %s, DECISION_NOTE = %s, DECIDED_BY = %s, DECIDED_AT = SYSDATE() "
                "WHERE REQUEST_ID = %s AND STATUS = 'OPEN'",
                (status, note, actor_id, request_id),
            )

    def get(self, request_id: str) -> Row | None:
        with service_cursor() as cur:
            return fetch_one(
                cur,
                f"SELECT {COLUMNS} FROM SECURITY.DRUG_REQUEST WHERE REQUEST_ID = %s",
                (request_id,),
            )

    @staticmethod
    def names(user_ids: set[str]) -> dict[str, str]:
        if not user_ids:
            return {}
        marks = ", ".join(["%s"] * len(user_ids))
        with service_cursor() as cur:
            rows = fetch_all(
                cur,
                f"SELECT USER_ID, DISPLAY_NAME FROM SECURITY.APP_USER WHERE USER_ID IN ({marks})",
                tuple(user_ids),
            )
        return {r["user_id"]: r["display_name"] for r in rows}

    # Public corpus and the caller's own patients ------------------------------------------------------------
    def indexed_names(self, role: str) -> set[str]:
        """Every name, alias and brand of an indexed drug, lower-case."""
        with user_cursor(role) as cur:
            rows = fetch_all(
                cur,
                "SELECT n.NAME_TEXT AS N FROM KNOWLEDGE.DRUG_NAME_MAP n JOIN KNOWLEDGE.DRUG d "
                "ON d.DRUG_ID = n.DRUG_ID AND d.IN_CORPUS UNION SELECT LOWER(DISPLAY_NAME) FROM KNOWLEDGE.DRUG WHERE IN_CORPUS",
            )
        return {r["n"] for r in rows}

    def coverage(self, role: str) -> CoverageData:
        with user_cursor(role) as cur:
            head = fetch_one(
                cur,
                "SELECT COUNT(*) AS KNOWN, COUNT_IF(IN_CORPUS) AS INDEXED, COUNT_IF(IN_NLEM) AS NLEM_KNOWN, "
                "COUNT_IF(IN_NLEM AND IN_CORPUS) AS NLEM_INDEXED FROM KNOWLEDGE.DRUG",
            )
            gaps = fetch_all(
                cur,
                "SELECT DISPLAY_NAME FROM KNOWLEDGE.DRUG WHERE NOT IN_CORPUS ORDER BY DISPLAY_NAME",
            )
            snap = fetch_one(
                cur, "SELECT SNAPSHOT_DATE, CHUNK_COUNT FROM KNOWLEDGE.SNAPSHOT LIMIT 1"
            )
            unlabelled = fetch_all(
                cur,
                "SELECT LOWER(COALESCE(DRUG_NAME, DESCRIPTION)) AS MEDICINE, COUNT(DISTINCT PATIENT_ID) AS PATIENTS "
                "FROM CLINICAL.MEDICATION WHERE IS_ACTIVE AND NOT IS_ARCHIVED AND DRUG_ID IS NULL "
                "AND COALESCE(DRUG_NAME, DESCRIPTION) IS NOT NULL GROUP BY 1 ORDER BY PATIENTS DESC, MEDICINE LIMIT 15",
            )
        with service_cursor() as cur:
            open_n = fetch_one(
                cur, "SELECT COUNT(*) AS N FROM SECURITY.DRUG_REQUEST WHERE STATUS = 'OPEN'"
            )
        return CoverageData(
            head=head or {}, gaps=[g["display_name"] for g in gaps], snapshot=snap or {}, unlabelled=unlabelled,
            open_requests=int(open_n["n"]) if open_n else 0,
        )  # fmt: skip
