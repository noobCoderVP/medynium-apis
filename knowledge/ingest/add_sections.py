"""Add the label sections the drug-information route needs (Indications and usage, Adverse reactions) to KNOWLEDGE.*.

The first load kept only safety sections, so "what is this drug used for" and "which drugs treat X" had nothing to find.
The raw openFDA JSON already holds those sections; this script chunks them from `raw/openfda/` and inserts them for
documents that do not have them yet. It only inserts: existing chunk ids never change (stored answers keep opening in the
Why? panel), and a second run adds nothing.

Dry run by default. Order: `python knowledge/ingest/add_sections.py --apply` -> rebuild the search index (DROP CORTEX
SEARCH SERVICE KNOWLEDGE.LABEL_SEARCH via `db.py sql`, then `db.py apply 50`) -> `db.py apply 30`."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "scripts"))

from catalog import load_drugs  # noqa: E402
from chunking import NEW_SECTIONS, approx_tokens, label_chunks  # noqa: E402
from load import SOURCE  # noqa: E402
from sfadmin import build_vars, connect  # noqa: E402

RAW = HERE.parent / "raw" / "openfda"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply", action="store_true", help="write to Snowflake (default: report only)"
    )
    args = parser.parse_args()
    conn = connect("MED_ADMIN", build_vars()["DB"])
    cur = conn.cursor()
    cur.execute(f"USE WAREHOUSE {build_vars()['WH']}")
    cur.execute(
        "SELECT COALESCE(MAX(TRY_TO_NUMBER(SUBSTR(CHUNK_ID, 4))), 0) FROM KNOWLEDGE.DOCUMENT_CHUNK"
    )
    chunk_no = int(cur.fetchone()[0])
    cur.execute("SELECT DOCUMENT_ID, DRUG_ID, SECTION_KEY FROM KNOWLEDGE.DOCUMENT_CHUNK")
    have: dict[str, set[str]] = {}
    for doc_id, _, key in cur.fetchall():
        have.setdefault(doc_id, set()).add(key)
    cur.execute(
        "SELECT DOCUMENT_ID, DRUG_ID, TITLE, VERSION_LABEL, EFFECTIVE_DATE FROM KNOWLEDGE.DOCUMENT"
    )
    docs = {row[0]: row for row in cur.fetchall()}
    cur.execute("SELECT DRUG_ID, DISPLAY_NAME FROM KNOWLEDGE.DRUG")
    names = dict(cur.fetchall())
    rows: list[tuple] = []
    for drug in load_drugs():
        doc_id = f"DOC-{drug['code']}-001"
        raw = RAW / f"{drug['code']}.json"
        if doc_id not in docs or not raw.exists() or drug.get("otc"):
            continue
        payload = json.loads(raw.read_text(encoding="utf-8"))
        _, drug_id, title, version, eff = docs[doc_id]
        for piece in label_chunks(payload["record"], sections=NEW_SECTIONS):
            if piece["section_key"] in have.get(doc_id, set()):
                continue
            chunk_no += 1
            name = names.get(drug_id) or drug["name"]
            rows.append(
                (f"CH-{chunk_no:04d}", doc_id, piece["section_key"], piece["section_name"], piece["index"], piece["text"],
                 f"{name} | {piece['section_name']} | {piece['text']}", approx_tokens(piece["text"]), drug_id, name, eff,
                 version, SOURCE, title, date.fromisoformat(payload["retrieved_at"][:10]))
            )  # fmt: skip
    print(f"{len(rows)} new chunks for {len({r[1] for r in rows})} documents")
    if rows and args.apply:
        cur.executemany(
            "INSERT INTO KNOWLEDGE.DOCUMENT_CHUNK (CHUNK_ID, DOCUMENT_ID, SECTION_KEY, SECTION_NAME, CHUNK_INDEX, TEXT, SEARCH_TEXT, TOKEN_COUNT, "
            "DRUG_ID, DRUG_NAME, EFFECTIVE_DATE, VERSION_LABEL, SOURCE, TITLE, RETRIEVED_DATE) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            rows,
        )
        print("inserted; now rebuild the search index (see the module docstring)")
    elif rows:
        print("dry run: nothing written (pass --apply)")
    conn.close()


if __name__ == "__main__":
    main()
