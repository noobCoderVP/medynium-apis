"""Load the corpus into KNOWLEDGE.* (K-4). Idempotent: ids come from drug code and section order, tables are rebuilt.

Run order: fetch_openfda.py -> load.py -> `db.py apply 25` (link medications) -> `db.py apply 50` (search service)
-> `db.py apply 30` (analytics read models pick up the links).
"""

import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "scripts"))

from chunking import approx_tokens, label_chunks  # noqa: E402
from india_brands import build as indian_brands  # noqa: E402
from sfadmin import build_vars, connect  # noqa: E402

RAW = HERE.parent / "raw" / "openfda"
SOURCE = "openFDA drug labeling"
LICENSE = "openFDA terms and license: https://open.fda.gov/license/"


def effective(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except (ValueError, TypeError):
        return None


def main() -> None:
    drugs = yaml.safe_load((HERE / "drugs.yaml").read_text(encoding="utf-8"))["drugs"]
    conflict = yaml.safe_load((HERE / "conflict_pair.yaml").read_text(encoding="utf-8"))
    brands = indian_brands({d["code"]: {a.lower() for a in d["aliases"]} for d in drugs})
    conn = connect("MED_ADMIN", build_vars()["DB"])
    cur = conn.cursor()
    cur.execute(f"USE WAREHOUSE {build_vars()['WH']}")
    for table in ("DOCUMENT_CHUNK", "DOCUMENT", "DRUG_NAME_MAP", "DRUG", "SNAPSHOT"):
        cur.execute(f"TRUNCATE TABLE KNOWLEDGE.{table}")

    chunk_no = 0
    documents = 0
    map_rows: list[tuple] = []
    chunk_rows: list[tuple] = []
    for number, drug in enumerate(drugs, start=1):
        drug_id = f"DRG-{number:03d}"
        path = RAW / f"{drug['code']}.json"
        if not path.exists():
            sys.exit(f"Missing {path}; run fetch_openfda.py first")
        payload = json.loads(path.read_text(encoding="utf-8"))
        record = payload["record"]
        cur.execute(
            "INSERT INTO KNOWLEDGE.DRUG (DRUG_ID, GENERIC_NAME, DISPLAY_NAME, IN_CORPUS, IN_NLEM) VALUES (%s,%s,%s,TRUE,%s)",
            (drug_id, drug["aliases"][0].lower(), drug["name"], bool(drug.get("nlem"))),
        )
        names = [(a.lower(), "SYNTHEA_INGREDIENT", "SYNTHEA", None) for a in drug["aliases"]]
        names += [(b, "INDIAN_BRAND", "AZ_INDIA", None) for b in brands.get(drug["code"], [])]
        for index, (text, kind, source, comp) in enumerate(names, start=1):
            map_rows.append((f"MAP-{drug['code']}-{index:02d}", drug_id, text, kind, source, comp))
        doc_id = f"DOC-{drug['code']}-001"
        title = f"{drug['name']} tablets: prescribing information"
        version = f"Label version {record.get('version', '?')}"
        eff = effective(record.get("effective_time", ""))
        chunks = label_chunks(record)
        content_hash = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        cur.execute(
            "INSERT INTO KNOWLEDGE.DOCUMENT (DOCUMENT_ID, DRUG_ID, SOURCE, DOC_TYPE, TITLE, VERSION_LABEL, EFFECTIVE_DATE, RETRIEVED_AT, INGESTED_AT, "
            "SOURCE_URL, LICENSE_NOTE, SOURCE_META, CONTENT_HASH) SELECT %s,%s,%s,'DRUG_LABEL',%s,%s,%s,%s,SYSDATE(),%s,%s,PARSE_JSON(%s),%s",
            (doc_id, drug_id, SOURCE, title, version, eff, payload["retrieved_at"].replace("T", " ").replace("Z", ""),
             payload["source_url"], LICENSE,
             json.dumps({"set_id": record.get("set_id"), "id": record.get("id"), "brand_names": record.get("openfda", {}).get("brand_name", [])[:5],
                         "manufacturers": record.get("openfda", {}).get("manufacturer_name", [])[:3], "rxcui": record.get("openfda", {}).get("rxcui", [])[:6]}),
             content_hash),
        )  # fmt: skip
        documents += 1
        for chunk in chunks:
            chunk_no += 1
            chunk_rows.append(
                (f"CH-{chunk_no:04d}", doc_id, chunk["section_key"], chunk["section_name"], chunk["index"], chunk["text"],
                 f"{drug['name']} | {chunk['section_name']} | {chunk['text']}", approx_tokens(chunk["text"]), drug_id, drug["name"], eff,
                 version, SOURCE, title, date.fromisoformat(payload["retrieved_at"][:10]))
            )  # fmt: skip

    # The deliberate conflict pair: a TEST document for furosemide with differing wording and an older version.
    fur_no = next(i for i, d in enumerate(drugs, start=1) if d["code"] == conflict["drug_code"])
    fur = drugs[fur_no - 1]
    cur.execute(
        "INSERT INTO KNOWLEDGE.DOCUMENT (DOCUMENT_ID, DRUG_ID, SOURCE, DOC_TYPE, TITLE, VERSION_LABEL, EFFECTIVE_DATE, RETRIEVED_AT, INGESTED_AT, "
        "SOURCE_URL, LICENSE_NOTE, SOURCE_META, CONTENT_HASH) SELECT %s,%s,%s,'DRUG_LABEL',%s,%s,%s,SYSDATE(),SYSDATE(),NULL,%s,PARSE_JSON(%s),%s",
        (f"DOC-{conflict['code']}", f"DRG-{fur_no:03d}", conflict["source"], conflict["title"], conflict["version_label"],
         date.fromisoformat(conflict["effective_date"]), conflict["license_note"], json.dumps({"test_data": True}), "test"),
    )  # fmt: skip
    documents += 1
    for index, section in enumerate(conflict["sections"]):
        chunk_no += 1
        chunk_rows.append(
            (f"CH-{chunk_no:04d}", f"DOC-{conflict['code']}", section["key"], section["name"], index, section["text"],
             f"{fur['name']} | {section['name']} | {section['text']}", approx_tokens(section["text"]), f"DRG-{fur_no:03d}", fur["name"],
             date.fromisoformat(conflict["effective_date"]), conflict["version_label"], conflict["source"], conflict["title"],
             date.fromisoformat(build_vars()["AS_OF"]))
        )  # fmt: skip

    cur.executemany(
        "INSERT INTO KNOWLEDGE.DRUG_NAME_MAP (MAP_ID, DRUG_ID, NAME_TEXT, NAME_KIND, SOURCE, COMPOSITION_TEXT) VALUES (%s,%s,%s,%s,%s,%s)",
        map_rows,
    )
    cur.executemany(
        "INSERT INTO KNOWLEDGE.DOCUMENT_CHUNK (CHUNK_ID, DOCUMENT_ID, SECTION_KEY, SECTION_NAME, CHUNK_INDEX, TEXT, SEARCH_TEXT, TOKEN_COUNT, "
        "DRUG_ID, DRUG_NAME, EFFECTIVE_DATE, VERSION_LABEL, SOURCE, TITLE, RETRIEVED_DATE) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        chunk_rows,
    )
    cur.execute(
        "INSERT INTO KNOWLEDGE.SNAPSHOT SELECT %s::DATE, (SELECT COUNT(*) FROM KNOWLEDGE.DOCUMENT), (SELECT COUNT(*) FROM KNOWLEDGE.DOCUMENT_CHUNK), "
        "(SELECT COUNT(*) FROM KNOWLEDGE.DRUG), %s",
        (
            build_vars()["AS_OF"],
            "openFDA labels fetched 2026-10-03; includes one clearly labelled test document for conflict display",
        ),
    )
    cur.execute("SELECT COUNT(*) FROM KNOWLEDGE.DOCUMENT_CHUNK")
    print(
        f"loaded {len(drugs)} drugs, {documents} documents, {cur.fetchone()[0]} chunks; Indian brands: {sum(len(v) for v in brands.values())}"
    )
    conn.close()


if __name__ == "__main__":
    main()
