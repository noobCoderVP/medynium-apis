"""Generate the synthetic population with a fixed seed (D-4). Output: data/synthea/out/csv/*.csv.

Settings are fixed so reruns are identical: population 300, adults 35 to 90 (so chronic conditions and
medicines are common), reference date = DEMO_AS_OF_DATE, CSV only (FHIR off).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JAR = ROOT / "synthea" / "synthea-with-dependencies.jar"
OUT = ROOT / "synthea" / "out"
SEED = 20261003
POPULATION = 300


def main() -> None:
    if not JAR.exists():
        sys.exit(
            f"Missing {JAR}. Download synthea-with-dependencies.jar from the Synthea releases page."
        )
    as_of = os.environ.get("DEMO_AS_OF_DATE", "2026-10-02").replace("-", "")
    if OUT.exists():
        shutil.rmtree(OUT)
    command = [
        "java", "-jar", str(JAR),
        "-s", str(SEED), "-cs", str(SEED), "-p", str(POPULATION), "-a", "35-90", "-r", as_of,
        f"--exporter.baseDirectory={OUT}",
        "--exporter.csv.export=true",
        "--exporter.fhir.export=false",
        "--exporter.hospital.fhir.export=false",
        "--exporter.practitioner.fhir.export=false",
    ]  # fmt: skip
    subprocess.run(command, check=True)
    files = sorted((OUT / "csv").glob("*.csv"))
    print(f"Generated {len(files)} CSV files in {OUT / 'csv'}")


if __name__ == "__main__":
    main()
