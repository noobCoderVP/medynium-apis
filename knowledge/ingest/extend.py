"""Add the catalog's new drugs to KNOWLEDGE.* without touching anything already there (production plan Phase 4).

load.py rebuilds the whole corpus, and it also rebuilds the Indian brand map from a dataset that is not in this repository,
so running it again would drop those brands. This script only inserts: a drug already present (matched by generic name) is
left exactly as it is, so stored answers that cite earlier chunk ids keep opening in the Why? panel. Run it as many times as
you like; the second run adds nothing.

Order of a refresh: fetch_openfda.py -> extend.py -> `db.py apply 25` (link medications) -> rebuild the search index
(DROP CORTEX SEARCH SERVICE KNOWLEDGE.LABEL_SEARCH, then `db.py apply 50`) -> `db.py apply 30` (read models).

A drug with no saved label (marked `no_label`, or openFDA had none) is still added, with IN_CORPUS false and its names and
brands, so a search says "not indexed" and the medication list shows the same honest gap, instead of guessing."""

import hashlib
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "scripts"))

from catalog import load_drugs  # noqa: E402
from chunking import approx_tokens, label_chunks  # noqa: E402
from load import LICENSE, SOURCE, effective  # noqa: E402
from sfadmin import build_vars, connect  # noqa: E402

RAW = HERE.parent / "raw" / "openfda"


def main() -> None:
    drugs = load_drugs()
    conn = connect("MED_ADMIN", build_vars()["DB"])
    cur = conn.cursor()
    cur.execute(f"USE WAREHOUSE {build_vars()['WH']}")
    cur.execute("SELECT GENERIC_NAME FROM KNOWLEDGE.DRUG")
    have = {r[0] for r in cur.fetchall()}
    cur.execute(
        "SELECT COALESCE(MAX(TRY_TO_NUMBER(SUBSTR(CHUNK_ID, 4))), 0) FROM KNOWLEDGE.DOCUMENT_CHUNK"
    )
    chunk_no = int(cur.fetchone()[0])
    added = indexed = 0
    maps: list[tuple] = []
    chunks: list[tuple] = []
    for position, drug in enumerate(drugs, start=1):
        generic = drug["aliases"][0].lower()
        if generic in have:
            continue
        drug_id = f"DRG-{position:03d}"
        raw = RAW / f"{drug['code']}.json"
        has_label = raw.exists() and not drug.get("no_label")
        cur.execute(
            "INSERT INTO KNOWLEDGE.DRUG (DRUG_ID, GENERIC_NAME, DISPLAY_NAME, IN_CORPUS, IN_NLEM) VALUES (%s,%s,%s,%s,%s)",
            (drug_id, generic, drug["name"], has_label, bool(drug.get("nlem"))),
        )
        names = [(a.lower(), "ALTERNATE_GENERIC", "MANUAL") for a in drug["aliases"]]
        names += [(b.lower(), "INDIAN_BRAND", "MANUAL") for b in drug.get("brands", [])]
        for index, (text, kind, source) in enumerate(names, start=1):
            maps.append((f"MAP-{drug['code']}-{index:02d}", drug_id, text, kind, source, None))
        added += 1
        if not has_label:
            print(
                f"added {drug_id} {drug['name']}: no label indexed ({'catalog says none' if drug.get('no_label') else 'none fetched'})"
            )
            continue
        payload = json.loads(raw.read_text(encoding="utf-8"))
        record = payload["record"]
        doc_id = f"DOC-{drug['code']}-001"
        title = f"{drug['name']}: {'Drug Facts label' if drug.get('otc') else 'prescribing information'}"
        version = f"Label version {record.get('version', '?')}"
        eff = effective(record.get("effective_time", ""))
        pieces = label_chunks(record, otc=bool(drug.get("otc")))
        cur.execute(
            "INSERT INTO KNOWLEDGE.DOCUMENT (DOCUMENT_ID, DRUG_ID, SOURCE, DOC_TYPE, TITLE, VERSION_LABEL, EFFECTIVE_DATE, RETRIEVED_AT, INGESTED_AT, "
            "SOURCE_URL, LICENSE_NOTE, SOURCE_META, CONTENT_HASH) SELECT %s,%s,%s,'DRUG_LABEL',%s,%s,%s,%s,SYSDATE(),%s,%s,PARSE_JSON(%s),%s",
            (doc_id, drug_id, SOURCE, title, version, eff, payload["retrieved_at"].replace("T", " ").replace("Z", ""),
             payload["source_url"], LICENSE,
             json.dumps({"set_id": record.get("set_id"), "id": record.get("id"), "brand_names": record.get("openfda", {}).get("brand_name", [])[:5],
                         "manufacturers": record.get("openfda", {}).get("manufacturer_name", [])[:3], "rxcui": record.get("openfda", {}).get("rxcui", [])[:6]}),
             hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()),
        )  # fmt: skip
        for piece in pieces:
            chunk_no += 1
            chunks.append(
                (f"CH-{chunk_no:04d}", doc_id, piece["section_key"], piece["section_name"], piece["index"], piece["text"],
                 f"{drug['name']} | {piece['section_name']} | {piece['text']}", approx_tokens(piece["text"]), drug_id, drug["name"], eff,
                 version, SOURCE, title, date.fromisoformat(payload["retrieved_at"][:10]))
            )  # fmt: skip
        indexed += 1
        print(f"added {drug_id} {drug['name']}: {len(pieces)} chunks")
    if maps:
        cur.executemany(
            "INSERT INTO KNOWLEDGE.DRUG_NAME_MAP (MAP_ID, DRUG_ID, NAME_TEXT, NAME_KIND, SOURCE, COMPOSITION_TEXT) VALUES (%s,%s,%s,%s,%s,%s)",
            maps,
        )
    if chunks:
        cur.executemany(
            "INSERT INTO KNOWLEDGE.DOCUMENT_CHUNK (CHUNK_ID, DOCUMENT_ID, SECTION_KEY, SECTION_NAME, CHUNK_INDEX, TEXT, SEARCH_TEXT, TOKEN_COUNT, "
            "DRUG_ID, DRUG_NAME, EFFECTIVE_DATE, VERSION_LABEL, SOURCE, TITLE, RETRIEVED_DATE) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            chunks,
        )
    if added:
        today = datetime.now(UTC).date()
        cur.execute("DELETE FROM KNOWLEDGE.SNAPSHOT")
        cur.execute(
            "INSERT INTO KNOWLEDGE.SNAPSHOT SELECT %s::DATE, (SELECT COUNT(*) FROM KNOWLEDGE.DOCUMENT), "
            "(SELECT COUNT(*) FROM KNOWLEDGE.DOCUMENT_CHUNK), (SELECT COUNT(*) FROM KNOWLEDGE.DRUG), %s",
            (
                today.isoformat(),
                f"openFDA labels fetched up to {today}; includes one clearly labelled test document for conflict display. US labelling: Indian labelling may differ.",
            ),
        )
    cur.execute("SELECT COUNT(*), COUNT_IF(IN_CORPUS) FROM KNOWLEDGE.DRUG")
    total, with_label = cur.fetchone()
    print(
        f"added {added} drugs ({indexed} with a label, {chunk_no} chunks in total); the corpus now lists {total} drugs, {with_label} indexed"
    )
    conn.close()


if __name__ == "__main__":
    main()
