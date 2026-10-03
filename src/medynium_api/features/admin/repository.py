"""Admin SQL under the service role: accounts, invitations and entitlements (never patient data)."""

import json
from typing import Any

from medynium_api.core.snowflake.queries import Row, execute, fetch_all, fetch_one, json_value
from medynium_api.core.snowflake.role_session import service_cursor

USER_SELECT = (
    "SELECT u.USER_ID, u.EMAIL, u.DISPLAY_NAME, u.ROLE_CODE, u.IS_ADMIN, u.STATUS, u.SUPERVISING_DOCTOR_ID, "
    "u.LAST_LOGIN_AT, (SELECT COUNT(*) FROM SECURITY.PATIENT_ENTITLEMENT e WHERE e.USER_ID = u.USER_ID "
    "AND e.REVOKED_AT IS NULL) AS PATIENT_COUNT FROM SECURITY.APP_USER u"
)


class AdminRepository:
    def list_users(
        self, q: str | None, role: str | None, status: str | None, limit: int, offset: int
    ) -> tuple[list[Row], int]:
        where, params = ["TRUE"], []
        if q:
            where.append("(u.DISPLAY_NAME ILIKE %s OR u.EMAIL ILIKE %s)")
            params += [f"%{q}%", f"%{q}%"]
        if role:
            where.append("u.ROLE_CODE = %s")
            params.append(role)
        if status:
            where.append("u.STATUS = %s")
            params.append(status)
        with service_cursor() as cur:
            rows = fetch_all(
                cur,
                f"{USER_SELECT} WHERE {' AND '.join(where)} ORDER BY u.DISPLAY_NAME LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
            total = fetch_one(
                cur,
                f"SELECT COUNT(*) AS N FROM SECURITY.APP_USER u WHERE {' AND '.join(where)}",
                params,
            )
        return rows, int(total["n"]) if total else 0

    def user(self, user_id: str) -> Row | None:
        with service_cursor() as cur:
            return fetch_one(cur, f"{USER_SELECT} WHERE u.USER_ID = %s", (user_id,))

    def admin_count(self) -> int:
        with service_cursor() as cur:
            row = fetch_one(
                cur,
                "SELECT COUNT(*) AS N FROM SECURITY.APP_USER WHERE IS_ADMIN AND STATUS = 'ACTIVE' AND ROLE_CODE = 'DOCTOR'",
            )
        return int(row["n"]) if row else 0

    def update_user(self, user_id: str, display_name: str | None, is_admin: bool | None) -> None:
        with service_cursor() as cur:
            execute(
                cur,
                "UPDATE SECURITY.APP_USER SET DISPLAY_NAME = COALESCE(%s, DISPLAY_NAME), IS_ADMIN = COALESCE(%s, IS_ADMIN), "
                "TOKEN_VERSION = TOKEN_VERSION + IFF(%s IS NULL, 0, 1) WHERE USER_ID = %s",
                (display_name, is_admin, is_admin, user_id),
            )

    def call(self, procedure: str, args: tuple[Any, ...]) -> dict[str, Any]:
        """Call one of the owner's-rights procedures; the name is fixed in code, never from input."""
        placeholders = ", ".join(["%s"] * len(args))
        with service_cursor() as cur:
            cur.execute(f"CALL SECURITY.{procedure}({placeholders})", args)
            return json_value(next(iter(cur.fetchone().values())))  # type: ignore[no-any-return]

    def set_entitlements(
        self, user_id: str, patient_ids: list[str], granted_by: str
    ) -> dict[str, Any]:
        with service_cursor() as cur:
            cur.execute(
                "CALL SECURITY.SET_ENTITLEMENTS(%s, PARSE_JSON(%s), %s)",
                (user_id, json.dumps(patient_ids), granted_by),
            )
            return json_value(next(iter(cur.fetchone().values())))  # type: ignore[no-any-return]

    def entitlements(self, user_id: str) -> list[str]:
        with service_cursor() as cur:
            rows = fetch_all(
                cur,
                "SELECT PATIENT_ID FROM SECURITY.PATIENT_ENTITLEMENT WHERE USER_ID = %s AND REVOKED_AT IS NULL "
                "ORDER BY PATIENT_ID",
                (user_id,),
            )
        return [r["patient_id"] for r in rows]

    def revoke_sessions(self, user_id: str) -> None:
        with service_cursor() as cur:
            execute(
                cur,
                "UPDATE SECURITY.AUTH_SESSION SET REVOKED_AT = SYSDATE() WHERE USER_ID = %s AND REVOKED_AT IS NULL",
                (user_id,),
            )

    # Invitations ------------------------------------------------------------------------------------------------
    def email_taken(self, email: str) -> bool:
        with service_cursor() as cur:
            row = fetch_one(
                cur,
                "SELECT (SELECT COUNT(*) FROM SECURITY.APP_USER WHERE EMAIL = %s) + (SELECT COUNT(*) FROM "
                "SECURITY.USER_INVITE WHERE EMAIL = %s AND KIND = 'INVITE' AND STATUS = 'PENDING' AND EXPIRES_AT > SYSDATE()) AS N",
                (email, email),
            )
        return bool(row and row["n"])

    def create_invite(self, values: tuple[Any, ...]) -> None:
        with service_cursor() as cur:
            execute(
                cur,
                "INSERT INTO SECURITY.USER_INVITE (INVITE_ID, EMAIL, DISPLAY_NAME, ROLE_CODE, IS_ADMIN, SUPERVISING_DOCTOR_ID, "
                "PATIENT_IDS, TOKEN_HASH, KIND, EXPIRES_AT, INVITED_BY, CREATED_AT) "
                "SELECT %s, %s, %s, %s, %s, %s, PARSE_JSON(%s), %s, %s, DATEADD('hour', %s, SYSDATE()), %s, SYSDATE()",
                values,
            )

    def invites(self) -> list[Row]:
        with service_cursor() as cur:
            return fetch_all(
                cur,
                "SELECT INVITE_ID, EMAIL, DISPLAY_NAME, ROLE_CODE, KIND, IFF(STATUS = 'PENDING' AND EXPIRES_AT < SYSDATE(), "
                "'EXPIRED', STATUS) AS STATUS, EXPIRES_AT, CREATED_AT FROM SECURITY.USER_INVITE ORDER BY CREATED_AT DESC LIMIT 200",
            )

    def revoke_invite(self, invite_id: str) -> int:
        with service_cursor() as cur:
            return execute(
                cur,
                "UPDATE SECURITY.USER_INVITE SET STATUS = 'REVOKED' WHERE INVITE_ID = %s AND STATUS = 'PENDING'",
                (invite_id,),
            )

    def supervisor_patient_ids(self, doctor_id: str) -> set[str]:
        return set(self.entitlements(doctor_id))
