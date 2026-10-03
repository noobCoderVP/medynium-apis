"""SQL for accounts, sessions and invitations. Runs under the service role (MED_API); never touches patient data."""

import json
from datetime import UTC, datetime
from typing import Any

from medynium_api.core.snowflake.queries import Row, execute, fetch_one, json_value
from medynium_api.core.snowflake.role_session import service_cursor

USER_COLUMNS = (
    "USER_ID, EMAIL, DISPLAY_NAME, ROLE_CODE, IS_ADMIN, SUPERVISING_DOCTOR_ID, STATUS, PASSWORD_HASH, "
    "FAILED_LOGINS, LOCKED_UNTIL, TOKEN_VERSION, SNOWFLAKE_ROLE"
)


class AuthRepository:
    def user_by_email(self, email: str) -> Row | None:
        with service_cursor() as cur:
            return fetch_one(
                cur, f"SELECT {USER_COLUMNS} FROM SECURITY.APP_USER WHERE EMAIL = %s", (email,)
            )

    def user_by_id(self, user_id: str) -> Row | None:
        with service_cursor() as cur:
            return fetch_one(
                cur, f"SELECT {USER_COLUMNS} FROM SECURITY.APP_USER WHERE USER_ID = %s", (user_id,)
            )

    def record_failure(self, user_id: str, max_failures: int, lock_minutes: int) -> None:
        with service_cursor() as cur:
            execute(
                cur,
                "UPDATE SECURITY.APP_USER SET FAILED_LOGINS = FAILED_LOGINS + 1, "
                "LOCKED_UNTIL = IFF(FAILED_LOGINS + 1 >= %s, DATEADD('minute', %s, SYSDATE()), LOCKED_UNTIL) "
                "WHERE USER_ID = %s",
                (max_failures, lock_minutes, user_id),
            )

    def record_success(self, user_id: str) -> None:
        with service_cursor() as cur:
            execute(
                cur,
                "UPDATE SECURITY.APP_USER SET FAILED_LOGINS = 0, LOCKED_UNTIL = NULL, LAST_LOGIN_AT = SYSDATE() "
                "WHERE USER_ID = %s",
                (user_id,),
            )

    def create_session(
        self,
        session_id: str,
        user_id: str,
        refresh_hash: str,
        days: int,
        user_agent: str | None,
        ip: str | None,
    ) -> None:
        with service_cursor() as cur:
            execute(
                cur,
                "INSERT INTO SECURITY.AUTH_SESSION (SESSION_ID, USER_ID, REFRESH_HASH, CREATED_AT, LAST_USED_AT, "
                "EXPIRES_AT, USER_AGENT, IP_ADDRESS) SELECT %s, %s, %s, SYSDATE(), SYSDATE(), "
                "DATEADD('day', %s, SYSDATE()), %s, %s",
                (session_id, user_id, refresh_hash, days, user_agent, ip),
            )

    def session(self, session_id: str) -> Row | None:
        with service_cursor() as cur:
            return fetch_one(
                cur,
                "SELECT SESSION_ID, USER_ID, REFRESH_HASH, PREVIOUS_HASH, EXPIRES_AT, REVOKED_AT, "
                "EXPIRES_AT < SYSDATE() AS EXPIRED FROM SECURITY.AUTH_SESSION WHERE SESSION_ID = %s",
                (session_id,),
            )

    def rotate_session(self, session_id: str, new_hash: str, old_hash: str) -> None:
        with service_cursor() as cur:
            execute(
                cur,
                "UPDATE SECURITY.AUTH_SESSION SET REFRESH_HASH = %s, PREVIOUS_HASH = %s, LAST_USED_AT = SYSDATE() "
                "WHERE SESSION_ID = %s",
                (new_hash, old_hash, session_id),
            )

    def revoke_session(self, session_id: str) -> None:
        with service_cursor() as cur:
            execute(
                cur,
                "UPDATE SECURITY.AUTH_SESSION SET REVOKED_AT = SYSDATE() WHERE SESSION_ID = %s AND REVOKED_AT IS NULL",
                (session_id,),
            )

    def revoke_user_sessions(self, user_id: str, except_session: str | None = None) -> None:
        with service_cursor() as cur:
            execute(
                cur,
                "UPDATE SECURITY.AUTH_SESSION SET REVOKED_AT = SYSDATE() WHERE USER_ID = %s AND REVOKED_AT IS NULL "
                "AND SESSION_ID <> COALESCE(%s, '')",
                (user_id, except_session),
            )

    def set_password(self, user_id: str, password_hash: str) -> None:
        with service_cursor() as cur:
            execute(
                cur,
                "UPDATE SECURITY.APP_USER SET PASSWORD_HASH = %s, PASSWORD_UPDATED_AT = SYSDATE(), "
                "TOKEN_VERSION = TOKEN_VERSION + 1, FAILED_LOGINS = 0, LOCKED_UNTIL = NULL WHERE USER_ID = %s",
                (password_hash, user_id),
            )

    def patient_count(self, user_id: str) -> int:
        with service_cursor() as cur:
            row = fetch_one(
                cur,
                "SELECT COUNT(*) AS N FROM SECURITY.PATIENT_ENTITLEMENT WHERE USER_ID = %s AND REVOKED_AT IS NULL",
                (user_id,),
            )
        return int(row["n"]) if row else 0

    # Invitations and password resets ---------------------------------------------------------------------------
    def valid_invite(self, token_hash: str) -> Row | None:
        with service_cursor() as cur:
            row = fetch_one(
                cur,
                "SELECT INVITE_ID, EMAIL, DISPLAY_NAME, ROLE_CODE, IS_ADMIN, SUPERVISING_DOCTOR_ID, PATIENT_IDS, "
                "KIND, EXPIRES_AT, INVITED_BY FROM SECURITY.USER_INVITE "
                "WHERE TOKEN_HASH = %s AND STATUS = 'PENDING' AND EXPIRES_AT > SYSDATE()",
                (token_hash,),
            )
        if row:
            row["patient_ids"] = json_value(row["patient_ids"]) or []
        return row

    def create_reset(self, values: tuple[Any, ...]) -> None:
        """A self-service password-reset link. Same table and hashing as an admin-issued one."""
        with service_cursor() as cur:
            execute(
                cur,
                "UPDATE SECURITY.USER_INVITE SET STATUS = 'REVOKED' WHERE EMAIL = %s AND KIND = 'PASSWORD_RESET' "
                "AND STATUS = 'PENDING'",
                (values[1],),
            )
            execute(
                cur,
                "INSERT INTO SECURITY.USER_INVITE (INVITE_ID, EMAIL, DISPLAY_NAME, ROLE_CODE, IS_ADMIN, SUPERVISING_DOCTOR_ID, "
                "PATIENT_IDS, TOKEN_HASH, KIND, EXPIRES_AT, INVITED_BY, CREATED_AT) "
                "SELECT %s, %s, %s, %s, %s, %s, PARSE_JSON('[]'), %s, 'PASSWORD_RESET', DATEADD('hour', %s, SYSDATE()), %s, SYSDATE()",
                values,
            )

    def mark_invite_accepted(self, invite_id: str) -> None:
        with service_cursor() as cur:
            execute(
                cur,
                "UPDATE SECURITY.USER_INVITE SET STATUS = 'ACCEPTED', ACCEPTED_AT = SYSDATE() WHERE INVITE_ID = %s",
                (invite_id,),
            )

    def provision_user(self, args: tuple[Any, ...]) -> dict[str, Any]:
        with service_cursor() as cur:
            cur.execute("CALL SECURITY.PROVISION_USER(%s, %s, %s, %s, %s, %s, %s, %s)", args)
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


def utc_now() -> datetime:
    """Naive UTC, matching how Snowflake returns TIMESTAMP_NTZ."""
    return datetime.now(UTC).replace(tzinfo=None)
