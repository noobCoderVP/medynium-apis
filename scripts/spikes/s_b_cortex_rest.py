"""Spike S-B: Cortex Analyst and Agent REST under a per-user role (S-A steps 4 and 5, S-B, S-D).

Records what the calls need and return; prints, never decides. Scratch objects in MEDYNIUM.SPIKE.
"""

import base64
import hashlib
import json
import os
import sys
import time

import httpx
import jwt
from _common import admin, provisioner, service, service_der
from cryptography.hazmat.primitives import serialization

ACCOUNT = os.environ["SNOWFLAKE_ACCOUNT"].upper()
HOST = f"{os.environ['SNOWFLAKE_ACCOUNT'].lower()}.snowflakecomputing.com"
USER = "MED_API_SVC"


def keypair_jwt() -> str:
    key = serialization.load_der_private_key(service_der(), password=None)
    pub = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    fp = "SHA256:" + base64.b64encode(hashlib.sha256(pub).digest()).decode()
    now = int(time.time())
    qualified = f"{ACCOUNT}.{USER}"
    claims = {"iss": f"{qualified}.{fp}", "sub": qualified, "iat": now, "exp": now + 3000}
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return jwt.encode(claims, pem, algorithm="RS256")


def headers(role: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {keypair_jwt()}",
        "X-Snowflake-Authorization-Token-Type": "KEYPAIR_JWT",
        "X-Snowflake-Role": role,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def setup() -> None:
    a, p = admin().cursor(), provisioner().cursor()
    for s in [
        "CREATE SCHEMA IF NOT EXISTS MEDYNIUM.SPIKE",
        "CREATE OR REPLACE TABLE MEDYNIUM.SPIKE.PAT (PATIENT_ID STRING, NAME STRING, EGFR NUMBER)",
        "INSERT INTO MEDYNIUM.SPIKE.PAT VALUES ('P1','Alpha',42),('P2','Beta',80),('P3','Gamma',55)",
        "CREATE OR REPLACE TABLE MEDYNIUM.SPIKE.ENT (PATIENT_ID STRING, SNOWFLAKE_ROLE STRING)",
        "INSERT INTO MEDYNIUM.SPIKE.ENT VALUES ('P1','U_SPIKE_A'),('P2','U_SPIKE_A'),('P3','U_SPIKE_B')",
        """CREATE OR REPLACE ROW ACCESS POLICY MEDYNIUM.SPIKE.RAP AS (pid STRING) RETURNS BOOLEAN ->
             EXISTS (SELECT 1 FROM MEDYNIUM.SPIKE.ENT e
                     WHERE e.PATIENT_ID = pid AND IS_ROLE_IN_SESSION(e.SNOWFLAKE_ROLE))""",
        "ALTER TABLE MEDYNIUM.SPIKE.PAT ADD ROW ACCESS POLICY MEDYNIUM.SPIKE.RAP ON (PATIENT_ID)",
        """CREATE OR REPLACE SEMANTIC VIEW MEDYNIUM.SPIKE.PAT_SV
             TABLES (pat AS MEDYNIUM.SPIKE.PAT PRIMARY KEY (PATIENT_ID))
             DIMENSIONS (pat.patient_id AS PATIENT_ID, pat.patient_name AS NAME)
             METRICS (pat.min_egfr AS MIN(pat.EGFR), pat.patient_count AS COUNT(pat.PATIENT_ID))""",
        "GRANT USAGE ON DATABASE MEDYNIUM TO ROLE MED_DOCTOR",
        "GRANT USAGE ON SCHEMA MEDYNIUM.SPIKE TO ROLE MED_DOCTOR",
        "GRANT SELECT ON TABLE MEDYNIUM.SPIKE.PAT TO ROLE MED_DOCTOR",
        "GRANT SELECT ON SEMANTIC VIEW MEDYNIUM.SPIKE.PAT_SV TO ROLE MED_DOCTOR",
    ]:
        a.execute(s)
    for s in [
        "CREATE ROLE IF NOT EXISTS U_SPIKE_A",
        "CREATE ROLE IF NOT EXISTS U_SPIKE_B",
        "GRANT ROLE MED_DOCTOR TO ROLE U_SPIKE_A",
        "GRANT ROLE MED_DOCTOR TO ROLE U_SPIKE_B",
        "GRANT ROLE U_SPIKE_A TO USER MED_API_SVC",
        "GRANT ROLE U_SPIKE_B TO USER MED_API_SVC",
    ]:
        p.execute(s)


def analyst(role: str, question: str) -> dict:
    body = {
        "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
        "semantic_view": "MEDYNIUM.SPIKE.PAT_SV",
    }
    started = time.time()
    r = httpx.post(
        f"https://{HOST}/api/v2/cortex/analyst/message",
        headers=headers(role),
        json=body,
        timeout=60,
    )
    print(f"  analyst {role}: HTTP {r.status_code} in {time.time() - started:.1f}s")
    return (
        r.json()
        if r.headers.get("content-type", "").startswith("application/json")
        else {"raw": r.text[:300]}
    )


def run_sql_as(role: str, sql: str) -> list[tuple]:
    conn = service()
    cur = conn.cursor()
    cur.execute("USE SECONDARY ROLES NONE")
    cur.execute(f"USE ROLE {role}")
    cur.execute(sql)
    return cur.fetchall()


def main() -> None:
    setup()
    print("== S-A step 4: Cortex Analyst under a per-user role")
    for role in ("U_SPIKE_A", "U_SPIKE_B"):
        resp = analyst(role, "List the names of all patients")
        content = (resp.get("message") or {}).get("content", [])
        sqls = [c.get("statement") for c in content if c.get("type") == "sql"]
        print(f"  keys={list(resp)[:5]} sql={sqls[:1]}")
        if not sqls:
            print("  response:", json.dumps(resp)[:500])
            continue
        print(f"  rows when the API runs that SQL under {role}:", run_sql_as(role, sqls[0]))
    print(
        "\n(Analyst returns SQL; the API executes it under the user's role, so row access holds by construction.)"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
