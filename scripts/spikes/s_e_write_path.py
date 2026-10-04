"""Spike S-E (P1.0): how does a write check the caller's entitlement?

Three designs are compared on scratch objects in MEDYNIUM.SPIKE_E (dropped at the end):
  (a) the caller writes directly under their own U_ role, relying on the row access policy;
  (b) the caller CALLs an owner's-rights procedure that checks INVOKER_ROLE() against the entitlement table;
  (f) the service role CALLs an owner's-rights procedure that takes the verified actor's user id and checks it
      against a user-keyed entitlement table (the PROVISION_USER pattern); U_ roles hold no write grants.
Run: python scripts/spikes/s_e_write_path.py
"""

import sys

from _common import admin, provisioner, service

SETUP_ADMIN = [
    "CREATE SCHEMA IF NOT EXISTS MEDYNIUM.SPIKE_E",
    "CREATE OR REPLACE TABLE MEDYNIUM.SPIKE_E.NOTE (PATIENT_ID STRING, BODY STRING, WRITER STRING)",
    "CREATE OR REPLACE TABLE MEDYNIUM.SPIKE_E.ENT (PATIENT_ID STRING, SNOWFLAKE_ROLE STRING)",
    "INSERT INTO MEDYNIUM.SPIKE_E.ENT VALUES ('P1','U_SPIKE_A'),('P2','U_SPIKE_A'),('P3','U_SPIKE_B')",
    """CREATE OR REPLACE ROW ACCESS POLICY MEDYNIUM.SPIKE_E.RAP AS (pid STRING) RETURNS BOOLEAN ->
         EXISTS (SELECT 1 FROM MEDYNIUM.SPIKE_E.ENT e
                 WHERE e.PATIENT_ID = pid AND IS_ROLE_IN_SESSION(e.SNOWFLAKE_ROLE))""",
    "ALTER TABLE MEDYNIUM.SPIKE_E.NOTE ADD ROW ACCESS POLICY MEDYNIUM.SPIKE_E.RAP ON (PATIENT_ID)",
    "INSERT INTO MEDYNIUM.SPIKE_E.NOTE VALUES ('P1','seed one','admin'),('P3','seed three','admin')",
    """CREATE OR REPLACE PROCEDURE MEDYNIUM.SPIKE_E.ADD_NOTE(P_PATIENT VARCHAR, P_BODY VARCHAR)
       RETURNS VARCHAR LANGUAGE SQL EXECUTE AS OWNER AS
       $$
       DECLARE who VARCHAR DEFAULT INVOKER_ROLE(); ok NUMBER DEFAULT 0;
       BEGIN
         SELECT COUNT(*) INTO :ok FROM MEDYNIUM.SPIKE_E.ENT WHERE PATIENT_ID = :P_PATIENT AND SNOWFLAKE_ROLE = :who;
         IF (ok = 0) THEN RETURN 'DENIED invoker=' || who; END IF;
         INSERT INTO MEDYNIUM.SPIKE_E.NOTE VALUES (:P_PATIENT, :P_BODY, :who);
         RETURN 'OK invoker=' || who || ' current=' || CURRENT_ROLE();
       END;
       $$""",
    "CREATE OR REPLACE TABLE MEDYNIUM.SPIKE_E.ENT_USER (PATIENT_ID STRING, USER_ID STRING)",
    "INSERT INTO MEDYNIUM.SPIKE_E.ENT_USER VALUES ('P1','user-a'),('P2','user-a'),('P3','user-b')",
    """CREATE OR REPLACE PROCEDURE MEDYNIUM.SPIKE_E.ADD_NOTE_ACTOR(P_ACTOR VARCHAR, P_PATIENT VARCHAR, P_BODY VARCHAR)
       RETURNS VARCHAR LANGUAGE SQL EXECUTE AS OWNER AS
       $$
       DECLARE ok NUMBER DEFAULT 0;
       BEGIN
         SELECT COUNT(*) INTO :ok FROM MEDYNIUM.SPIKE_E.ENT_USER WHERE PATIENT_ID = :P_PATIENT AND USER_ID = :P_ACTOR;
         IF (ok = 0) THEN RETURN 'DENIED'; END IF;
         INSERT INTO MEDYNIUM.SPIKE_E.NOTE VALUES (:P_PATIENT, :P_BODY, :P_ACTOR);
         RETURN 'OK';
       END;
       $$""",
    "GRANT USAGE ON SCHEMA MEDYNIUM.SPIKE_E TO ROLE MED_API",
    "GRANT USAGE ON PROCEDURE MEDYNIUM.SPIKE_E.ADD_NOTE_ACTOR(VARCHAR, VARCHAR, VARCHAR) TO ROLE MED_API",
    "GRANT USAGE ON SCHEMA MEDYNIUM.SPIKE_E TO ROLE MED_DOCTOR",
    "GRANT USAGE ON DATABASE MEDYNIUM TO ROLE MED_DOCTOR",
    "GRANT USAGE ON PROCEDURE MEDYNIUM.SPIKE_E.ADD_NOTE(VARCHAR, VARCHAR) TO ROLE MED_DOCTOR",
    "GRANT SELECT, INSERT, UPDATE ON TABLE MEDYNIUM.SPIKE_E.NOTE TO ROLE MED_DOCTOR",
]
SETUP_PROV = [
    "CREATE ROLE IF NOT EXISTS U_SPIKE_A",
    "CREATE ROLE IF NOT EXISTS U_SPIKE_B",
    "GRANT ROLE MED_DOCTOR TO ROLE U_SPIKE_A",
    "GRANT ROLE MED_DOCTOR TO ROLE U_SPIKE_B",
    "GRANT ROLE U_SPIKE_A TO USER MED_API_SVC",
    "GRANT ROLE U_SPIKE_B TO USER MED_API_SVC",
]
TEARDOWN_ADMIN = ["DROP SCHEMA IF EXISTS MEDYNIUM.SPIKE_E"]
TEARDOWN_PROV = ["DROP ROLE IF EXISTS U_SPIKE_A", "DROP ROLE IF EXISTS U_SPIKE_B"]

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if detail else ""))


def run(conn: object, statements: list[str]) -> None:
    cur = conn.cursor()  # type: ignore[attr-defined]
    for stmt in statements:
        cur.execute(stmt)


def main() -> None:
    a, p = admin(), provisioner()
    run(a, SETUP_ADMIN)
    run(p, SETUP_PROV)
    svc = service()
    cur = svc.cursor()
    cur.execute("USE WAREHOUSE MEDYNIUM_WH")
    try:
        # (a) direct writes under the user's own role
        cur.execute("USE SECONDARY ROLES NONE")
        cur.execute("USE ROLE U_SPIKE_A")
        cur.execute("INSERT INTO MEDYNIUM.SPIKE_E.NOTE VALUES ('P3','A writes for B patient','A')")
        record("a: INSERT for a patient the caller is NOT entitled to is not blocked by the policy", True,
               "the policy does not check inserts, so the API check is mandatory")  # fmt: skip
        cur.execute("UPDATE MEDYNIUM.SPIKE_E.NOTE SET BODY = 'tampered' WHERE PATIENT_ID = 'P3'")
        record("a: UPDATE of a non-entitled patient's row changes nothing", (cur.rowcount or 0) == 0,
               f"rows={cur.rowcount}")  # fmt: skip
        cur.execute("UPDATE MEDYNIUM.SPIKE_E.NOTE SET BODY = 'edited' WHERE PATIENT_ID = 'P1'")
        record(
            "a: UPDATE of an entitled patient's row works",
            (cur.rowcount or 0) == 1,
            f"rows={cur.rowcount}",
        )

        # (b) owner's-rights procedure checking INVOKER_ROLE(): expected NOT to identify the caller
        cur.execute("CALL MEDYNIUM.SPIKE_E.ADD_NOTE('P1', 'via procedure by A')")
        out = cur.fetchone()[0]
        record("b: INVOKER_ROLE() inside an owner's-rights procedure does NOT identify the caller",
               "invoker=U_SPIKE_A" not in out, out)  # fmt: skip

        # (f) service role calls an owner's-rights procedure with the verified actor id
        cur.execute("USE ROLE MED_API")
        cur.execute("CALL MEDYNIUM.SPIKE_E.ADD_NOTE_ACTOR('user-a', 'P1', 'via actor procedure')")
        record("f: entitled actor is accepted", cur.fetchone()[0] == "OK")
        cur.execute(
            "CALL MEDYNIUM.SPIKE_E.ADD_NOTE_ACTOR('user-a', 'P3', 'a writes for b patient')"
        )
        record("f: non-entitled actor is denied inside Snowflake", cur.fetchone()[0] == "DENIED")
        cur.execute("CALL MEDYNIUM.SPIKE_E.ADD_NOTE_ACTOR('nobody', 'P1', 'unknown actor')")
        record("f: an unknown actor is denied", cur.fetchone()[0] == "DENIED")
        try:
            cur.execute(
                "INSERT INTO MEDYNIUM.SPIKE_E.NOTE VALUES ('P1','direct insert as service','svc')"
            )
            record("f: the service role cannot write the table directly", False)
        except Exception:
            record("f: the service role cannot write the table directly", True)
        cur.execute("USE ROLE U_SPIKE_A")
        try:
            cur.execute(
                "CALL MEDYNIUM.SPIKE_E.ADD_NOTE_ACTOR('user-a', 'P1', 'caller via U_ role')"
            )
            record("f: a U_ role cannot reach the procedure by accident", False, "it could call it")
        except Exception:
            record("f: a U_ role is not granted the actor procedure", True)
    finally:
        try:
            cur.execute("USE ROLE MED_API")
        finally:
            svc.close()
            run(a, TEARDOWN_ADMIN)
            run(p, TEARDOWN_PROV)
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks as expected")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
