"""Spike S-A: does a per-user role, assumed by the service user, drive row access policies?

Steps 1 to 3 and 6 of the Stage 0 spikes (docs/architecture/spikes.md). Steps 4 and 5 (Cortex Analyst and Agent) are in
s_b_cortex_rest.py. Scratch objects live in MEDYNIUM.SPIKE and are dropped at the end.
"""

import sys
import threading

from _common import admin, provisioner, service

SETUP_ADMIN = [
    "CREATE SCHEMA IF NOT EXISTS MEDYNIUM.SPIKE",
    "CREATE OR REPLACE TABLE MEDYNIUM.SPIKE.PAT (PATIENT_ID STRING, NAME STRING)",
    "INSERT INTO MEDYNIUM.SPIKE.PAT VALUES ('P1','Alpha'),('P2','Beta'),('P3','Gamma')",
    "CREATE OR REPLACE TABLE MEDYNIUM.SPIKE.ENT (PATIENT_ID STRING, SNOWFLAKE_ROLE STRING)",
    "INSERT INTO MEDYNIUM.SPIKE.ENT VALUES ('P1','U_SPIKE_A'),('P2','U_SPIKE_A'),('P3','U_SPIKE_B')",
    """CREATE OR REPLACE ROW ACCESS POLICY MEDYNIUM.SPIKE.RAP AS (pid STRING) RETURNS BOOLEAN ->
         EXISTS (SELECT 1 FROM MEDYNIUM.SPIKE.ENT e
                 WHERE e.PATIENT_ID = pid AND IS_ROLE_IN_SESSION(e.SNOWFLAKE_ROLE))""",
    "ALTER TABLE MEDYNIUM.SPIKE.PAT ADD ROW ACCESS POLICY MEDYNIUM.SPIKE.RAP ON (PATIENT_ID)",
    "GRANT USAGE ON SCHEMA MEDYNIUM.SPIKE TO ROLE MED_DOCTOR",
    "GRANT SELECT ON TABLE MEDYNIUM.SPIKE.PAT TO ROLE MED_DOCTOR",
    "GRANT USAGE ON DATABASE MEDYNIUM TO ROLE MED_DOCTOR",
]
SETUP_PROV = [
    "CREATE ROLE IF NOT EXISTS U_SPIKE_A",
    "CREATE ROLE IF NOT EXISTS U_SPIKE_B",
    "CREATE ROLE IF NOT EXISTS U_SPIKE_NOGRANT",
    "GRANT ROLE MED_DOCTOR TO ROLE U_SPIKE_A",
    "GRANT ROLE MED_DOCTOR TO ROLE U_SPIKE_B",
    "GRANT ROLE MED_DOCTOR TO ROLE U_SPIKE_NOGRANT",
    "GRANT ROLE U_SPIKE_A TO USER MED_API_SVC",
    "GRANT ROLE U_SPIKE_B TO USER MED_API_SVC",
]
TEARDOWN_ADMIN = ["DROP SCHEMA IF EXISTS MEDYNIUM.SPIKE"]
TEARDOWN_PROV = [
    "DROP ROLE IF EXISTS U_SPIKE_A",
    "DROP ROLE IF EXISTS U_SPIKE_B",
    "DROP ROLE IF EXISTS U_SPIKE_NOGRANT",
]

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if detail else ""))


def run(conn: object, statements: list[str]) -> None:
    cur = conn.cursor()  # type: ignore[attr-defined]
    for stmt in statements:
        cur.execute(stmt)


def names(cur: object) -> list[str]:
    cur.execute("SELECT NAME FROM MEDYNIUM.SPIKE.PAT ORDER BY 1")  # type: ignore[attr-defined]
    return [r[0] for r in cur.fetchall()]  # type: ignore[attr-defined]


def main() -> None:
    a, p = admin(), provisioner()
    run(a, SETUP_ADMIN)
    run(p, SETUP_PROV)

    svc = service()
    cur = svc.cursor()

    try:
        cur.execute("SELECT COUNT(*) FROM MEDYNIUM.SPIKE.PAT")
        record("MED_API alone has no access to patient tables", False, "query succeeded")
    except Exception as exc:  # noqa: BLE001
        record("MED_API alone has no access to patient tables", True, str(exc).splitlines()[0][:80])

    cur.execute("USE SECONDARY ROLES NONE")
    cur.execute("USE ROLE U_SPIKE_A")
    record("Step 2: U_A sees only A's patients", names(cur) == ["Alpha", "Beta"], str(names(cur)))
    cur.execute("USE ROLE U_SPIKE_B")
    record("Step 3: switching to U_B flips the result", names(cur) == ["Gamma"], str(names(cur)))
    cur.execute("USE ROLE U_SPIKE_A")
    record(
        "Step 3b: switching back leaks nothing", names(cur) == ["Alpha", "Beta"], str(names(cur))
    )

    try:
        cur.execute("USE ROLE U_SPIKE_NOGRANT")
        record("A role not granted to the service user is refused", False, "USE ROLE succeeded")
    except Exception:  # noqa: BLE001
        record("A role not granted to the service user is refused", True)

    cur.execute("USE ROLE MED_API")
    try:
        cur.execute("SELECT COUNT(*) FROM MEDYNIUM.SPIKE.PAT")
        record("Reset to MED_API removes access again", False, "query succeeded")
    except Exception:  # noqa: BLE001
        record("Reset to MED_API removes access again", True)

    # Step 6: concurrent connections with different roles, 100 alternating queries each.
    leaks: list[str] = []

    def worker(role: str, expected: list[str]) -> None:
        conn = service()
        c = conn.cursor()
        c.execute("USE SECONDARY ROLES NONE")
        c.execute(f"USE ROLE {role}")
        for _ in range(100):
            got = names(c)
            if got != expected:
                leaks.append(f"{role} saw {got}")
                return

    threads = [
        threading.Thread(target=worker, args=("U_SPIKE_A", ["Alpha", "Beta"])),
        threading.Thread(target=worker, args=("U_SPIKE_B", ["Gamma"])),
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    record("Step 6: concurrent roles do not cross-talk (200 queries)", not leaks, "; ".join(leaks))

    run(a, TEARDOWN_ADMIN)
    run(p, TEARDOWN_PROV)
    failed = [r for r in results if not r[1]]
    print("\nS-A (SQL steps):", "PASS" if not failed else f"FAIL ({len(failed)})")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
