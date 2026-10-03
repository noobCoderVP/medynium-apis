"""Seed the three demo accounts through PROVISION_USER and SET_ENTITLEMENTS (D-7), the path real invites use.

Passwords are generated here and written to ~/.medynium/demo_credentials.txt (outside the repo). Existing
accounts keep their passwords unless --reset-passwords is given. Entitlements are re-applied every run.

Entitlements: Dr. Sharma gets the seeded patients (incl. S3) and half of the generated ones; the second
doctor gets the other half (proves cross-doctor isolation); the assistant gets a subset of Sharma's
patients that excludes S3.
"""

import argparse
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sfadmin import KEY_DIR, connect  # noqa: E402

from medynium_api.core.ids import new_uuid  # noqa: E402
from medynium_api.core.security.passwords import hash_password  # noqa: E402

CREDENTIALS = KEY_DIR.parent / "demo_credentials.txt"
SEEDED = ["P-1042", "P-1067", "P-1093", "P-1101", "P-1118", "P-1126", "P-1133"]
S3 = "P-1093"
USERS = [
    {"email": "sharma@demo.medynium", "name": "Dr. Sharma", "role": "DOCTOR", "admin": True},
    {"email": "second.doctor@demo.medynium", "name": "Dr. Rao", "role": "DOCTOR", "admin": False},
    {
        "email": "assistant@demo.medynium",
        "name": "Meera Joshi",
        "role": "ASSISTANT",
        "admin": False,
    },
]


def load_credentials() -> dict[str, str]:
    if not CREDENTIALS.exists():
        return {}
    pairs = (
        line.split(" ", 1)
        for line in CREDENTIALS.read_text(encoding="utf-8").splitlines()
        if " " in line
    )
    return {email: password for email, password in pairs}


def call(cur: object, statement: str, params: tuple) -> dict:
    cur.execute(statement, params)  # type: ignore[attr-defined]
    return json.loads(cur.fetchone()[0])  # type: ignore[attr-defined]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset-passwords", action="store_true")
    args = parser.parse_args()

    conn = connect("MED_ADMIN", "MEDYNIUM")
    cur = conn.cursor()
    cur.execute("USE WAREHOUSE MEDYNIUM_WH")
    credentials = load_credentials()
    ids: dict[str, str] = {}
    cur.execute("SELECT EMAIL, USER_ID FROM SECURITY.APP_USER")
    existing = {email: uid for email, uid in cur.fetchall()}

    for user in USERS:
        email = user["email"]
        if email in existing:
            ids[email] = existing[email]
            if args.reset_passwords or email not in credentials:
                password = secrets.token_urlsafe(15)
                cur.execute(
                    "UPDATE SECURITY.APP_USER SET PASSWORD_HASH = %s, PASSWORD_UPDATED_AT = SYSDATE(), "
                    "FAILED_LOGINS = 0, LOCKED_UNTIL = NULL, TOKEN_VERSION = TOKEN_VERSION + 1 WHERE EMAIL = %s",
                    (hash_password(password), email),
                )
                credentials[email] = password
            print(f"exists: {email}")
            continue
        password = secrets.token_urlsafe(15)
        supervisor = ids.get("sharma@demo.medynium") if user["role"] == "ASSISTANT" else None
        uid = new_uuid()
        result = call(
            cur,
            "CALL SECURITY.PROVISION_USER(%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                uid,
                email,
                user["name"],
                user["role"],
                user["admin"],
                supervisor,
                hash_password(password),
                None,
            ),
        )
        if not result.get("ok"):
            sys.exit(f"PROVISION_USER failed for {email}: {result}")
        ids[email] = uid
        credentials[email] = password
        print(f"provisioned: {email} -> {result['snowflake_role']}")

    cur.execute(
        "SELECT PATIENT_ID FROM CLINICAL.PATIENT WHERE PATIENT_ID LIKE 'P-2%' ORDER BY PATIENT_ID"
    )
    generated = [r[0] for r in cur.fetchall()]
    sharma_generated, second_generated = generated[0::2], generated[1::2]
    sharma_ids = SEEDED + sharma_generated
    assistant_ids = [p for p in SEEDED if p != S3] + sharma_generated[:30]

    plan = [
        ("sharma@demo.medynium", sharma_ids),
        ("second.doctor@demo.medynium", second_generated),
        ("assistant@demo.medynium", assistant_ids),  # after Sharma: must be a subset of hers
    ]
    for email, patient_ids in plan:
        result = call(
            cur,
            "CALL SECURITY.SET_ENTITLEMENTS(%s, PARSE_JSON(%s), %s)",
            (ids[email], json.dumps(patient_ids), ids["sharma@demo.medynium"]),
        )
        if not result.get("ok"):
            sys.exit(f"SET_ENTITLEMENTS failed for {email}: {result}")
        print(f"entitled: {email} to {result['count']} patients")

    CREDENTIALS.write_text(
        "\n".join(f"{e} {p}" for e, p in credentials.items()) + "\n", encoding="utf-8"
    )
    print(f"credentials in {CREDENTIALS} (outside the repo)")
    conn.close()


if __name__ == "__main__":
    main()
