"""A tiny PDF writer for synthetic sample reports: real text on each page, no library. Used by gen_sample_reports.py and by
the live tests. Not product code and never run by the API."""

import io


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(pages: list[list[str]]) -> bytes:
    """One PDF with the given pages, each a list of text lines. Plain ASCII keeps the text layer exact."""
    objects: list[str] = []
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append("<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
    font_id = 3 + 2 * len(pages)
    for i, lines in enumerate(pages):
        content_id = 4 + 2 * i
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        )
        stream = (
            "BT /F1 11 Tf 50 750 Td 16 TL "
            + " ".join(f"({_escape(line)}) Tj T*" for line in lines)
            + " ET"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def lab_panel(
    name: str, collected: str | None, rows: list[tuple[str, str, str, str]], pid: str | None = None
) -> bytes:
    """A one-page lab report. Rows are (test, value, unit, reference range)."""
    head = [
        "CITY DIAGNOSTICS LABORATORY",
        "",
        f"Patient: {name}" + (f"    Patient ID: {pid}" if pid else ""),
    ]
    if collected:
        head.append(f"Sample collected: {collected}")
    head += ["", "Test                      Result      Unit        Reference"]
    body = [f"{test} {value} {unit} ({ref})" for test, value, unit, ref in rows]
    return build_pdf([head + body + ["", "End of report."]])
