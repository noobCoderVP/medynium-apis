"""Load the localised CSVs into RAW.* (D-5): PUT to the internal stage, COPY INTO with ON_ERROR = ABORT_STATEMENT.

RAW tables are created from each CSV header, all VARCHAR, so RAW always mirrors the file.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sfadmin import build_vars, connect  # noqa: E402

SRC = Path(__file__).resolve().parent / "synthea" / "localised"


def main() -> None:
    files = sorted(SRC.glob("*.csv"))
    if not files:
        sys.exit(f"No CSV files in {SRC}. Run data/generate_synthea.py and data/localise.py first.")
    db = build_vars()["DB"]
    conn = connect("MED_ADMIN", db)
    cur = conn.cursor()
    cur.execute(f"USE WAREHOUSE {build_vars()['WH']}")
    cur.execute("USE SCHEMA RAW")
    for path in files:
        table = path.stem.upper()
        with path.open(encoding="utf-8", newline="") as handle:
            header = next(csv.reader(handle))
        columns = ", ".join(f'"{c.upper()}" VARCHAR' for c in header)
        cur.execute(f"CREATE OR REPLACE TABLE RAW.{table} ({columns})")
        cur.execute(f"REMOVE @RAW.SYNTHEA_STAGE/{path.stem}/")
        cur.execute(
            f"PUT 'file://{path.as_posix()}' @RAW.SYNTHEA_STAGE/{path.stem}/ AUTO_COMPRESS=TRUE OVERWRITE=TRUE"
        )
        cur.execute(
            f"COPY INTO RAW.{table} FROM @RAW.SYNTHEA_STAGE/{path.stem}/ "
            "FILE_FORMAT = (FORMAT_NAME = RAW.CSV_FORMAT) ON_ERROR = ABORT_STATEMENT FORCE = TRUE"
        )
        cur.execute(f"SELECT COUNT(*) FROM RAW.{table}")
        print(f"RAW.{table}: {cur.fetchone()[0]} rows")
    conn.close()


if __name__ == "__main__":
    main()
