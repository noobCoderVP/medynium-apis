"""Fetch one label per in-scope generic from the openFDA API and save the raw JSON (K-2).

Ingestion only: nothing here runs at request time (NFR-12). Rules:
  - query by exact generic name; prescription labels, or Drug Facts labels for drugs marked `otc`;
  - keep only single-ingredient records (a plain query can return combination products);
  - choose the label with the latest effective_time that has the sections the corpus needs;
  - save the response unchanged under knowledge/raw/openfda/<code>.json before any processing.
A file that is already saved is not fetched again (so earlier citations never change underneath stored answers); pass
--refresh to re-fetch. A drug with no usable label does not stop the run: it is listed in raw/missing.json and the
reason is printed, because a thin or absent label is an honest gap, not an error. Drugs marked `no_label` are skipped.
Usage: python knowledge/ingest/fetch_openfda.py [--refresh] [--only CODE ...]
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from catalog import load_drugs  # noqa: E402

ROOT = HERE.parent
RAW = ROOT / "raw" / "openfda"
API = "https://api.fda.gov/drug/label.json"
NEEDED = (
    "contraindications",
    "warnings_and_cautions",
    "warnings",
    "dosage_and_administration",
    "use_in_specific_populations",
)
OTC_NEEDED = (
    "warnings",
    "do_not_use",
    "ask_doctor",
    "stop_use",
    "dosage_and_administration",
    "pregnancy_or_breast_feeding",
)
RX, OTC = "HUMAN PRESCRIPTION DRUG", "HUMAN OTC DRUG"


def fetch(client: httpx.Client, name: str, product_type: str) -> list[dict]:
    search = f'openfda.generic_name.exact:"{name}" AND openfda.product_type.exact:"{product_type}"'
    response = client.get(API, params={"search": search, "limit": 100}, timeout=60)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return response.json().get("results", [])


def pick(records: list[dict], names: set[str], needed: tuple[str, ...]) -> dict | None:
    single = [r for r in records if [n.upper() for n in r.get("openfda", {}).get("generic_name", [])] and
              {n.upper() for n in r["openfda"]["generic_name"]} <= names]  # fmt: skip
    usable = [r for r in single if sum(1 for k in needed if r.get(k)) >= 3]
    usable.sort(
        key=lambda r: (r.get("effective_time", ""), sum(1 for k in needed if r.get(k))),
        reverse=True,
    )
    return usable[0] if usable else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh", action="store_true", help="fetch again even when a file is saved"
    )
    parser.add_argument("--only", nargs="*", help="drug codes to fetch")
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    missing: dict[str, str] = {}
    fetched = skipped = 0
    with httpx.Client() as client:
        for drug in load_drugs():
            code = drug["code"]
            if args.only and code not in args.only:
                continue
            if drug.get("no_label"):
                continue
            path = RAW / f"{code}.json"
            if path.exists() and not args.refresh:
                skipped += 1
                continue
            names = {n.upper() for n in drug["openfda"]}
            otc = bool(drug.get("otc"))
            record = None
            for name in drug["openfda"]:
                record = pick(
                    fetch(client, name.upper(), OTC if otc else RX),
                    names,
                    OTC_NEEDED if otc else NEEDED,
                )
                if record:
                    break
                time.sleep(0.3)
            if not record:
                missing[code] = (
                    f"{drug['name']}: no single-ingredient {'OTC' if otc else 'prescription'} label with enough sections"
                )
                print(f"MISSING {code} {missing[code]}")
                continue
            payload = {
                "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "source_url": API,
                "query_names": drug["openfda"],
                "record": record,
            }
            path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            fetched += 1
            print(
                f"ok {code} {drug['name']}: set_id {record.get('set_id')} v{record.get('version')} effective {record.get('effective_time')}"
            )
            time.sleep(0.3)
    (RAW.parent / "missing.json").write_text(json.dumps(missing, indent=1), encoding="utf-8")
    print(f"fetched {fetched}, already saved {skipped}, missing {len(missing)}")


if __name__ == "__main__":
    main()
