"""Spike S-F (P2.0, P5.0): which Snowflake AI functions work in this account and region, and what do they cost in time?

Checks: text embeddings (for similar patients), document parsing of a stage file (for report upload), structured
extraction with a hosted model, and vector similarity. Scratch objects live in MEDYNIUM.SPIKE_F and are dropped.
Run: python scripts/spikes/s_f_ai_functions.py"""

import io
import sys
import time

from _common import admin

TEXT = "Female 58, type 2 diabetes mellitus, chronic kidney disease stage 3b; metformin 1000 mg, lisinopril; eGFR 42 low"
OTHER = "Male 61, diabetes mellitus type 2 with reduced kidney function; on metformin and ramipril; eGFR 45"
FAR = "Child 6, asthma, salbutamol inhaler as needed"


def timed(label: str, fn):  # type: ignore[no-untyped-def]
    started = time.time()
    try:
        value = fn()
        print(f"OK   {label}  ({time.time() - started:.1f}s)")
        return value
    except Exception as exc:
        print(f"FAIL {label}: {str(exc)[:240].replace(chr(10), ' ')}")
        return None


def tiny_pdf() -> bytes:
    """A one-page PDF with a lab table as real text, built by hand so the spike needs no library."""
    lines = [
        "Patient: Zz Spike Patient   Collected: 12 Sep 2026 08:15",
        "Haemoglobin A1c 8.1 % (ref < 7.0)",
        "eGFR 42 mL/min/1.73 m2 (ref > 60)",
    ]
    stream = "BT /F1 12 Tf 50 750 Td " + " ".join(f"({t}) Tj 0 -20 Td" for t in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{body}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def main() -> None:
    conn = admin()
    cur = conn.cursor()
    cur.execute("USE WAREHOUSE MEDYNIUM_WH")
    cur.execute("CREATE SCHEMA IF NOT EXISTS MEDYNIUM.SPIKE_F")
    cur.execute("USE SCHEMA MEDYNIUM.SPIKE_F")

    for model in (
        "snowflake-arctic-embed-l-v2.0",
        "snowflake-arctic-embed-m-v1.5",
        "snowflake-arctic-embed-m",
    ):
        got = timed(
            f"EMBED_TEXT_1024 {model}" if "l-v2" in model else f"EMBED_TEXT_768 {model}",
            lambda m=model: (
                cur.execute(
                    f"SELECT SNOWFLAKE.CORTEX.EMBED_TEXT_{'1024' if 'l-v2' in m else '768'}(%s, %s)",
                    (m, TEXT),
                ),
                cur.fetchone()[0],
            )[1],
        )
        if got is not None:
            print(f"     dimensions: {len(got) if hasattr(got, '__len__') else 'n/a'}")
            break

    def similarity() -> None:
        cur.execute(
            "SELECT VECTOR_COSINE_SIMILARITY(a, b), VECTOR_COSINE_SIMILARITY(a, c) FROM "
            "(SELECT SNOWFLAKE.CORTEX.EMBED_TEXT_1024('snowflake-arctic-embed-l-v2.0', %s) AS a, "
            "SNOWFLAKE.CORTEX.EMBED_TEXT_1024('snowflake-arctic-embed-l-v2.0', %s) AS b, "
            "SNOWFLAKE.CORTEX.EMBED_TEXT_1024('snowflake-arctic-embed-l-v2.0', %s) AS c)",
            (TEXT, OTHER, FAR),
        )
        near, far = cur.fetchone()
        print(f"     near-match similarity {near:.3f}, unrelated {far:.3f}")

    timed("VECTOR_COSINE_SIMILARITY on embeddings", similarity)

    # A stage and a text-layer PDF
    cur.execute(
        "CREATE OR REPLACE STAGE MEDYNIUM.SPIKE_F.DOCS ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE') DIRECTORY = (ENABLE = TRUE)"
    )
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp()) / "spike_report.pdf"
    tmp.write_bytes(tiny_pdf())
    timed(
        "PUT a PDF to an encrypted internal stage",
        lambda: cur.execute(
            f"PUT file://{tmp.as_posix()} @MEDYNIUM.SPIKE_F.DOCS AUTO_COMPRESS=FALSE OVERWRITE=TRUE"
        ),
    )
    for mode in ("OCR", "LAYOUT"):
        text = timed(
            f"PARSE_DOCUMENT mode={mode}",
            lambda m=mode: (
                cur.execute(
                    "SELECT SNOWFLAKE.CORTEX.PARSE_DOCUMENT('@MEDYNIUM.SPIKE_F.DOCS', 'spike_report.pdf', {'mode': %s})",
                    (m,),
                ),
                cur.fetchone()[0],
            )[1],
        )
        if text is not None:
            print("     ", str(text)[:200].replace("\n", " "))
    timed(
        "AI_PARSE_DOCUMENT (newer name)",
        lambda: (
            cur.execute(
                "SELECT AI_PARSE_DOCUMENT(TO_FILE('@MEDYNIUM.SPIKE_F.DOCS', 'spike_report.pdf'), {'mode': 'OCR'})"
            ),
            cur.fetchone()[0],
        )[1],
    )

    def extraction() -> None:
        cur.execute(
            "SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3.3-70b', PARSE_JSON(%s), PARSE_JSON(%s))",
            (
                '[{"role":"system","content":"Return ONLY JSON: {\\"rows\\":[{\\"test\\":str,\\"value\\":number,\\"unit\\":str}]}"},'
                '{"role":"user","content":"Haemoglobin A1c 8.1 % (ref < 7.0)  eGFR 42 mL/min/1.73 m2 (ref > 60)"}]',
                '{"max_tokens": 300, "temperature": 0}',
            ),
        )
        print("     ", str(cur.fetchone()[0])[:260].replace("\n", " "))

    timed("COMPLETE llama3.3-70b structured extraction", extraction)
    cur.execute("DROP SCHEMA IF EXISTS MEDYNIUM.SPIKE_F")
    conn.close()
    sys.exit(0)


if __name__ == "__main__":
    main()
