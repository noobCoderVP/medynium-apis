"""Fetch one label per in-scope generic from the openFDA API and save the raw JSON (K-2).

Ingestion only: nothing here runs at request time (NFR-12). Rules:
  - query by exact generic name and human prescription drugs;
  - keep only single-ingredient records (a plain query can return combination products);
  - choose the label with the latest effective_time that has the sections the demo needs;
  - save the response unchanged under knowledge/raw/openfda/<code>.json before any processing.
"""

import json
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw" / "openfda"
API = "https://api.fda.gov/drug/label.json"
NEEDED = (
    "contraindications",
    "warnings_and_cautions",
    "warnings",
    "dosage_and_administration",
    "use_in_specific_populations",
)


def fetch(client: httpx.Client, name: str) -> list[dict]:
    search = f'openfda.generic_name.exact:"{name}" AND openfda.product_type.exact:"HUMAN PRESCRIPTION DRUG"'
    response = client.get(API, params={"search": search, "limit": 100}, timeout=60)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return response.json().get("results", [])


def pick(records: list[dict], names: set[str]) -> dict | None:
    single = [r for r in records if [n.upper() for n in r.get("openfda", {}).get("generic_name", [])] and
              {n.upper() for n in r["openfda"]["generic_name"]} <= names]  # fmt: skip
    usable = [r for r in single if sum(1 for k in NEEDED if r.get(k)) >= 3]
    usable.sort(
        key=lambda r: (r.get("effective_time", ""), sum(1 for k in NEEDED if r.get(k))),
        reverse=True,
    )
    return usable[0] if usable else None


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    drugs = yaml.safe_load((ROOT / "ingest" / "drugs.yaml").read_text(encoding="utf-8"))["drugs"]
    missing: list[str] = []
    with httpx.Client() as client:
        for drug in drugs:
            names = {n.upper() for n in drug["openfda"]}
            record = None
            for name in drug["openfda"]:
                record = pick(fetch(client, name.upper()), names)
                if record:
                    break
                time.sleep(0.3)
            if not record:
                missing.append(drug["code"])
                print(f"MISSING {drug['code']} {drug['name']}")
                continue
            payload = {
                "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "source_url": API,
                "query_names": drug["openfda"],
                "record": record,
            }
            (RAW / f"{drug['code']}.json").write_text(
                json.dumps(payload, indent=1), encoding="utf-8"
            )
            print(
                f"ok {drug['code']} {drug['name']}: set_id {record.get('set_id')} v{record.get('version')} effective {record.get('effective_time')}"
            )
            time.sleep(0.3)
    if missing:
        sys.exit(
            f"No usable label for: {missing}. Replace them in drugs.yaml before building on this corpus."
        )


if __name__ == "__main__":
    main()
