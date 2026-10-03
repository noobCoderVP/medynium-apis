"""Database runner: the only way setup SQL is applied.

  python scripts/db.py bootstrap        run 00_bootstrap.sql as ACCOUNTADMIN (once)
  python scripts/db.py apply [prefix]   run numbered files (optionally only those starting with prefix)
  python scripts/db.py check            run 90_checks.sql and print the results
  python scripts/db.py status           object and row counts
  python scripts/db.py sql "<stmt>"     run one statement as MED_ADMIN and print rows

Files are idempotent: CREATE OR REPLACE / IF NOT EXISTS / MERGE.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sfadmin import ROOT, build_vars, connect, render, run_script  # noqa: E402

SQL_DIR = ROOT / "snowflake"
ADMIN_ROLE = "MED_ADMIN"


def numbered_files(prefix: str | None) -> list[Path]:
    files = sorted(p for p in SQL_DIR.glob("[0-9][0-9]_*.sql") if not p.name.startswith("00_"))
    return [p for p in files if prefix is None or p.name.startswith(prefix)]


def cmd_bootstrap() -> None:
    conn = connect("ACCOUNTADMIN")
    try:
        n = run_script(conn, SQL_DIR / "00_bootstrap.sql", build_vars())
        print(f"00_bootstrap.sql: {n} statements")
    finally:
        conn.close()


def cmd_apply(prefix: str | None) -> None:
    conn = connect(ADMIN_ROLE)
    try:
        for path in numbered_files(prefix):
            started = time.time()
            n = run_script(conn, path, build_vars())
            print(f"{path.name}: {n} statements in {time.time() - started:.1f}s")
    finally:
        conn.close()


def print_rows(cursor: object) -> None:
    rows = cursor.fetchall()  # type: ignore[attr-defined]
    cols = [c[0] for c in cursor.description]  # type: ignore[attr-defined]
    print(" | ".join(cols))
    for row in rows:
        print(" | ".join(str(v) for v in row))


def cmd_sql(statement: str) -> None:
    conn = connect(ADMIN_ROLE, build_vars()["DB"])
    try:
        cur = conn.cursor()
        cur.execute(f"USE WAREHOUSE {build_vars()['WH']}")
        cur.execute(statement)
        print_rows(cur)
    finally:
        conn.close()


def cmd_check() -> int:
    conn = connect(ADMIN_ROLE)
    failures = 0
    try:
        for cursor in conn.execute_string(
            render((SQL_DIR / "90_checks.sql").read_text(encoding="utf-8"), build_vars())
        ):
            if cursor.description and cursor.description[0][0] == "CHECK_NAME":
                for name, ok, detail in cursor.fetchall():
                    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail or ''}")
                    failures += 0 if ok else 1
    finally:
        conn.close()
    print("db check:", "green" if failures == 0 else f"{failures} failing")
    return failures


def cmd_status() -> None:
    conn = connect(ADMIN_ROLE, build_vars()["DB"])
    try:
        cur = conn.cursor()
        cur.execute(f"USE WAREHOUSE {build_vars()['WH']}")
        cur.execute(
            "SELECT table_schema, COUNT(*) AS table_count, SUM(row_count) AS row_total "
            "FROM MEDYNIUM.INFORMATION_SCHEMA.TABLES "
            "WHERE table_schema <> 'INFORMATION_SCHEMA' GROUP BY 1 ORDER BY 1"
        )
        print_rows(cur)
        print()
        try:  # credit use against the cap (F-6); needs the privilege to see the monitor
            cur.execute("SHOW RESOURCE MONITORS")
            for row in cur.fetchall():
                print(
                    "resource monitor:",
                    row[0],
                    "quota:",
                    row[1],
                    "used:",
                    row[2],
                    "remaining:",
                    row[3],
                )
        except Exception as exc:  # noqa: BLE001
            print("resource monitor: not visible to", ADMIN_ROLE, f"({type(exc).__name__})")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["bootstrap", "apply", "check", "status", "sql"])
    parser.add_argument("arg", nargs="?")
    args = parser.parse_args()
    if args.command == "bootstrap":
        cmd_bootstrap()
    elif args.command == "apply":
        cmd_apply(args.arg)
    elif args.command == "check":
        sys.exit(1 if cmd_check() else 0)
    elif args.command == "status":
        cmd_status()
    else:
        cmd_sql(args.arg)


if __name__ == "__main__":
    main()
