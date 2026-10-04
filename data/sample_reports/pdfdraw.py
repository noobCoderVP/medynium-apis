"""A small styled-PDF layer for the demo reports: A4 pages, colour, bold and italic type, shaded tables, tiles and a
barcode, with no library. Text stays real text (standard fonts, ASCII), so PARSE_DOCUMENT reads it exactly. Coordinates
run from the top-left, in points. Not product code and never run by the API."""

import io
import random

from pdfmaker import _escape

W, H, MARGIN = 595.28, 841.89, 36.0
CONTENT_W = W - 2 * MARGIN
_WIDTHS = [
    "278",
    "278",
    "355",
    "556",
    "556",
    "889",
    "667",
    "191",
    "333",
    "333",
    "389",
    "584",
    "278",
    "333",
    "278",
    "278",
    "556",
    "556",
    "556",
    "556",
    "556",
    "556",
    "556",
    "556",
    "556",
    "556",
    "278",
    "278",
    "584",
    "584",
    "584",
    "556",
    "1015",
    "667",
    "667",
    "722",
    "722",
    "667",
    "611",
    "778",
    "722",
    "278",
    "500",
    "667",
    "556",
    "833",
    "722",
    "778",
    "667",
    "778",
    "722",
    "667",
    "611",
    "722",
    "667",
    "944",
    "667",
    "667",
    "611",
    "278",
    "278",
    "278",
    "469",
    "556",
    "333",
    "556",
    "556",
    "500",
    "556",
    "556",
    "278",
    "556",
    "556",
    "222",
    "222",
    "500",
    "222",
    "833",
    "556",
    "556",
    "556",
    "556",
    "333",
    "500",
    "278",
    "556",
    "500",
    "722",
    "500",
    "500",
    "500",
    "334",
    "260",
    "334",
    "584",
]
WIDTH = {chr(32 + i): int(w) for i, w in enumerate(_WIDTHS)}


def text_width(text: str, size: float, bold: bool = False) -> float:
    return sum(WIDTH.get(c, 556) for c in text) * size / 1000 * (1.06 if bold else 1.0)


def wrap(text: str, size: float, width: float, bold: bool = False) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if text_width(trial, size, bold) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


def rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return " ".join(f"{int(h[i : i + 2], 16) / 255:.3f}" for i in (0, 2, 4))


class Page:
    def __init__(self) -> None:
        self.ops: list[str] = []
        self.y = 0.0  # the cursor: top of the next thing to place

    def rect(self, x: float, y: float, w: float, h: float, fill: str | None = None,
             stroke: str | None = None, lw: float = 0.6) -> None:  # fmt: skip
        parts = [f"{x:.2f} {H - y - h:.2f} {w:.2f} {h:.2f} re"]
        if fill:
            parts = [f"{rgb(fill)} rg", *parts, "f"]
            self.ops.append(" ".join(parts))
        if stroke:
            self.ops.append(f"{rgb(stroke)} RG {lw} w {x:.2f} {H - y - h:.2f} {w:.2f} {h:.2f} re S")

    def line(self, x1: float, x2: float, y: float, color: str = "#C9D1D9", lw: float = 0.5) -> None:
        self.ops.append(f"{rgb(color)} RG {lw} w {x1:.2f} {H - y:.2f} m {x2:.2f} {H - y:.2f} l S")

    def text(self, x: float, y: float, s: str, size: float = 9, font: str = "F1",
             color: str = "#1F2933") -> None:  # fmt: skip
        """`y` is the baseline."""
        self.ops.append(
            f"BT /{font} {size} Tf {rgb(color)} rg {x:.2f} {H - y:.2f} Td ({_escape(s)}) Tj ET"
        )

    def aligned(self, x: float, w: float, y: float, s: str, size: float, font: str, color: str,
                align: str = "l", pad: float = 5) -> None:  # fmt: skip
        tw = text_width(s, size, font == "F2")
        if tw > w - 2 * pad + 0.5:
            raise ValueError(f"cell text too wide for its column: {s!r}")
        left = {"l": x + pad, "r": x + w - pad - tw, "c": x + (w - tw) / 2}[align]
        self.text(left, y, s, size, font, color)

    # Building blocks ---------------------------------------------------------------------------------------------
    def letterhead(self, name: str, sub: str, right: list[str], accent: str, stripe: str) -> None:
        self.rect(0, 0, W, 74, fill=accent)
        self.rect(0, 74, W, 3.5, fill=stripe)
        self.rect(MARGIN, 18, 38, 38, fill="#FFFFFF")  # logo: a cross on a white tile
        self.rect(MARGIN + 15, 23, 8, 28, fill=accent)
        self.rect(MARGIN + 5, 33, 28, 8, fill=accent)
        self.text(MARGIN + 50, 34, name, 16, "F2", "#FFFFFF")
        self.text(MARGIN + 50, 49, sub, 8, "F1", "#E6EEF5")
        for i, line in enumerate(right):
            tw = text_width(line, 8)
            self.text(W - MARGIN - tw, 30 + i * 12, line, 8, "F1", "#E6EEF5")
        self.y = 92

    def title(self, title: str, accent: str, right: str = "") -> None:
        self.text(MARGIN, self.y + 12, title, 13, "F2", accent)
        if right:
            self.text(W - MARGIN - text_width(right, 8.5), self.y + 12, right, 8.5, "F1", "#52606D")
        self.line(MARGIN, W - MARGIN, self.y + 20, accent, 1.2)
        self.y += 30

    def info_box(self, pairs: list[tuple[str, str]], accent: str, label_w: float = 78) -> None:
        """Two columns of label and value."""
        rows = (len(pairs) + 1) // 2
        h = rows * 17 + 10
        self.rect(MARGIN, self.y, CONTENT_W, h, fill="#F4F7FA", stroke="#D5DDE5")
        self.rect(MARGIN, self.y, 3.5, h, fill=accent)
        col_w = CONTENT_W / 2
        for i, (label, value) in enumerate(pairs):
            x = MARGIN + 12 + (i % 2) * col_w
            base = self.y + 17 + (i // 2) * 17
            self.text(x, base, label, 8, "F1", "#6B7785")
            self.text(x + label_w, base, value, 9, "F2", "#1F2933")
        self.y += h + 14

    def section(self, title: str, accent: str) -> None:
        self.rect(MARGIN, self.y, CONTENT_W, 18, fill=accent)
        self.text(MARGIN + 8, self.y + 12.5, title, 9, "F2", "#FFFFFF")
        self.y += 18 + 8

    def subhead(self, title: str, tint: str, color: str) -> None:
        self.rect(MARGIN, self.y, CONTENT_W, 17, fill=tint)
        self.text(MARGIN + 8, self.y + 12, title, 8.5, "F2", color)
        self.y += 17

    def para(self, s: str, size: float = 9, color: str = "#323F4B", gap: float = 8) -> None:
        for line in wrap(s, size, CONTENT_W):
            self.text(MARGIN, self.y + size, line, size, "F1", color)
            self.y += size * 1.5
        self.y += gap

    def bullets(self, items: list[str], accent: str, size: float = 9) -> None:
        for item in items:
            lines = wrap(item, size, CONTENT_W - 16)
            self.rect(MARGIN + 3, self.y + size - 5.5, 4, 4, fill=accent)
            for line in lines:
                self.text(MARGIN + 14, self.y + size, line, size, "F1", "#323F4B")
                self.y += size * 1.5
            self.y += 2
        self.y += 6

    def table(self, cols: list[tuple[str, float, str]], rows: list[list], head: str, size: float = 8.5,
              row_h: float = 18, flag_tint: str = "#FDECEA") -> None:  # fmt: skip
        """cols: (title, width, align). A cell is a string or (string, style) where style may hold bold, color and
        tint (a row is tinted when any of its cells asks)."""
        x0 = MARGIN
        self.rect(x0, self.y, CONTENT_W, row_h, fill=head)
        x = x0
        for title, width, align in cols:
            self.aligned(x, width, self.y + row_h - 5.5, title, size - 0.5, "F2", "#FFFFFF", align)
            x += width
        self.y += row_h
        top = self.y - row_h
        for n, row in enumerate(rows):
            cells = [c if isinstance(c, tuple) else (c, {}) for c in row]
            tint = next((s["tint"] for _, s in cells if "tint" in s), None)
            self.rect(
                x0, self.y, CONTENT_W, row_h, fill=tint or ("#F7F9FB" if n % 2 else "#FFFFFF")
            )
            x = x0
            for (value, style), (_, width, align) in zip(cells, cols, strict=True):
                bold = style.get("bold", False)
                self.aligned(x, width, self.y + row_h - 5.5, value, size, "F2" if bold else "F1",
                             style.get("color", "#1F2933"), align)  # fmt: skip
                x += width
            self.line(x0, x0 + CONTENT_W, self.y + row_h, "#DDE3E9", 0.4)
            self.y += row_h
        self.rect(x0, top, CONTENT_W, self.y - top, stroke="#B8C2CC", lw=0.7)
        self.y += 12

    def tiles(self, items: list[tuple[str, str]], accent: str) -> None:
        gap = 8
        w = (CONTENT_W - gap * (len(items) - 1)) / len(items)
        for i, (label, value) in enumerate(items):
            x = MARGIN + i * (w + gap)
            self.rect(x, self.y, w, 40, fill="#FFFFFF", stroke=accent, lw=0.9)
            self.rect(x, self.y, w, 3, fill=accent)
            self.text(x + 8, self.y + 17, label, 7.5, "F1", "#6B7785")
            self.text(x + 8, self.y + 33, value, 11, "F2", "#1F2933")
        self.y += 40 + 14

    def callout(self, title: str, body: str, accent: str, tint: str) -> None:
        lines = wrap(body, 9, CONTENT_W - 24)
        h = 16 + 13 + len(lines) * 13.5 + 6
        self.rect(MARGIN, self.y, CONTENT_W, h, fill=tint)
        self.rect(MARGIN, self.y, 4, h, fill=accent)
        self.text(MARGIN + 14, self.y + 17, title, 9.5, "F2", accent)
        for i, line in enumerate(lines):
            self.text(MARGIN + 14, self.y + 32 + i * 13.5, line, 9, "F1", "#323F4B")
        self.y += h + 14

    def barcode(self, x: float, y: float, w: float, h: float, seed: int, caption: str) -> None:
        rnd = random.Random(seed)
        cx = x
        while cx < x + w:
            bar = rnd.choice([0.8, 1.2, 1.8, 2.4])
            self.rect(cx, y, bar, h, fill="#1F2933")
            cx += bar + rnd.choice([0.8, 1.2, 1.8])
        self.text(x, y + h + 9, caption, 7, "F1", "#52606D")

    def signature(self, x: float, script: str, lines: list[str], color: str = "#1B3A6B") -> None:
        self.text(x, self.y + 16, script, 18, "F3", color)
        self.line(x, x + 170, self.y + 24, "#7B8794", 0.6)
        for i, line in enumerate(lines):
            self.text(x, self.y + 36 + i * 11, line, 8.5 if i == 0 else 8, "F2" if i == 0 else "F1",
                      "#1F2933" if i == 0 else "#52606D")  # fmt: skip
        self.y += 36 + len(lines) * 11 + 6

    def footer(self, left: str, number: int, total: int, accent: str) -> None:
        if self.y > H - 52:
            raise ValueError(f"page {number} overflows its footer (cursor at {self.y:.0f})")
        self.line(MARGIN, W - MARGIN, H - 40, accent, 0.9)
        self.text(MARGIN, H - 28, left, 7.5, "F1", "#6B7785")
        label = f"Page {number} of {total}"
        self.text(W - MARGIN - text_width(label, 8, True), H - 28, label, 8, "F2", "#323F4B")


def build(pages: list[Page]) -> bytes:
    objects: list[str] = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
    font = 3 + 2 * len(pages)
    for i, page in enumerate(pages):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] /Contents {4 + 2 * i} 0 R /Resources << /Font "
            f"<< /F1 {font} 0 R /F2 {font + 1} 0 R /F3 {font + 2} 0 R >> >> >>"
        )
        stream = "\n".join(page.ops)
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    for name in ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique"):
        objects.append(
            f"<< /Type /Font /Subtype /Type1 /BaseFont /{name} /Encoding /WinAnsiEncoding >>"
        )
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
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
