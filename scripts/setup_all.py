"""One-command setup: runs every step of docs/database/data-loading.md in order, stopping on the first failure.

  python scripts/setup_all.py               run all steps
  python scripts/setup_all.py --dry-run     print the steps only
  python scripts/setup_all.py --from 7      resume at step 7 (numbers are shown by --dry-run)
  python scripts/setup_all.py --with-eval   also run the golden, injection and routing evals at the end

Every step is idempotent, so a failed run can simply be started again. Needs .env and the key pair
(`python scripts/gen_keypair.py`, once) and an ACCOUNTADMIN login for the two bootstrap steps.
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
DB = ["scripts/db.py"]
STEPS: list[tuple[str, list[str]]] = [
    ("bootstrap roles, warehouse, monitor (ACCOUNTADMIN)", [*DB, "bootstrap"]),
    ("schemas, tables, policies, procedures (01-09)", [*DB, "apply", "0"]),
    ("writer role (ACCOUNTADMIN)", [*DB, "bootstrap-writer"]),
    ("generate 300 synthetic patients", ["data/generate_synthea.py"]),
    ("localise to Indian identities and INR", ["data/localise.py"]),
    ("load RAW", ["data/load_raw.py"]),
    ("RAW -> CLINICAL", [*DB, "apply", "20"]),
    ("seed scenarios S1-S5 and fillers", ["data/seed_scenarios.py"]),
    ("generate notes", ["data/gen_notes.py"]),
    ("fetch openFDA labels", ["knowledge/ingest/fetch_openfda.py"]),
    ("load KNOWLEDGE", ["knowledge/ingest/load.py"]),
    ("link medicines to drugs", [*DB, "apply", "25"]),
    ("similar-patient and case-summary views (10-11)", [*DB, "apply", "1"]),
    ("read models, embeddings, refresh, intake and report procedures (30-37)", [*DB, "apply", "3"]),
    ("semantic view", [*DB, "apply", "40"]),
    ("search service", [*DB, "apply", "50"]),
    ("grants", [*DB, "apply", "60"]),
    ("demo users and entitlements", ["scripts/seed_users.py"]),
    ("integrity checks (must be green)", [*DB, "check"]),
]
EVALS = [
    ("routing eval", ["scripts/eval_routing.py"]),
    ("golden eval", ["scripts/eval_golden.py", "--set", "golden"]),
    ("injection eval", ["scripts/eval_golden.py", "--set", "injection"]),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from", dest="start", type=int, default=1)
    ap.add_argument("--with-eval", action="store_true")
    args = ap.parse_args()
    steps = STEPS + (EVALS if args.with_eval else [])
    for n, (label, cmd) in enumerate(steps, 1):
        if n < args.start:
            continue
        print(f"[{n}/{len(steps)}] {label}: python {' '.join(cmd)}", flush=True)
        if args.dry_run:
            continue
        if subprocess.run([PY, *cmd], cwd=ROOT, check=False).returncode:  # noqa: S603
            sys.exit(
                f"Step {n} failed. Fix it and resume with: python scripts/setup_all.py --from {n}"
            )
    print("Done." if not args.dry_run else "Dry run only.")


if __name__ == "__main__":
    main()
