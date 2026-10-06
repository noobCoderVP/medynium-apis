"""Write a styled one-page lab report for the demo hero Rahul Patel (P-1042), for the report-upload scene. Run:
python data/sample_reports/gen_rahul_lab_results.py

Output: data/sample_reports/lab_results_rahul_patel.pdf. Every test here is one the extractor recognises and the
seed record does not already hold (creatinine, haemoglobin, sodium, TSH, LDL), and it leaves out eGFR, HbA1c and
potassium on purpose: approving the report must not change the hero numbers the assistant quotes. Synthetic only."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdfdraw import MARGIN, Page, W, build  # noqa: E402

OUT = Path(__file__).resolve().parent / "lab_results_rahul_patel.pdf"
NAME = "Rahul Patel"
RED, BLUE = "#B3261E", "#1F5FBF"
HIGH = {"color": RED, "bold": True, "tint": "#FDECEA"}
LOW = {"color": BLUE, "bold": True, "tint": "#EAF1FD"}
NOTE = "Synthetic demo document, not for clinical use"


def lab_results() -> bytes:
    maroon, stripe = "#7A1F2B", "#D6A24B"
    foot = f"{NAME}  |  Patient ID P-1042  |  Sample 2610010388  |  {NOTE}"
    cols = [
        ("Test name", 185, "l"),
        ("Result", 62, "r"),
        ("Flag", 38, "c"),
        ("Unit", 100, "l"),
        ("Biological reference interval", 138, "l"),
    ]
    sub = ("#F6E9EB", maroon)

    p = Page()
    p.letterhead(
        "City Diagnostics Laboratory",
        "NABL accredited (MC-3487)  |  Navrangpura, Ahmedabad 380009",
        ["Tel 079-5550-0199", "reports@citydiagnostics.example"],
        maroon,
        stripe,
    )
    p.title("LABORATORY REPORT", maroon, "Abnormal results are highlighted")
    p.info_box(
        [
            ("Patient Name", NAME),
            ("Patient ID", "P-1042"),
            ("Age / Sex", "58 Y / Male"),
            ("Referred by", "Dr. Sharma"),
            ("Sample collected", "01/10/2026 07:50"),
            ("Reported on", "01/10/2026 14:05"),
        ],
        maroon,
        label_w=88,
    )
    p.barcode(W - MARGIN - 130, 84, 130, 15, 2610010388, "Sample ID 2610010388")
    p.section("BIOCHEMISTRY", maroon)
    p.subhead("RENAL FUNCTION", *sub)
    p.table(cols, [["Creatinine", ("1.8", HIGH), ("H", HIGH), "mg/dL", "0.6 - 1.3"]], maroon)
    p.subhead("ELECTROLYTES", *sub)
    p.table(cols, [["Sodium", "138", "", "mmol/L", "135 - 145"]], maroon)
    p.subhead("LIPID PROFILE", *sub)
    p.table(cols, [["LDL cholesterol", ("128", HIGH), ("H", HIGH), "mg/dL", "< 100"]], maroon)
    p.subhead("THYROID PROFILE", *sub)
    p.table(cols, [["TSH", "3.1", "", "mIU/L", "0.4 - 4.0"]], maroon)
    p.section("HAEMATOLOGY", maroon)
    p.subhead("COMPLETE BLOOD COUNT", *sub)
    p.table(cols, [["Haemoglobin", ("11.4", LOW), ("L", LOW), "g/dL", "13.0 - 17.0"]], maroon)
    p.para(
        "Comment: Interpret with the clinical picture. Results relate only to the sample tested.",
        size=8,
        color="#52606D",
    )
    p.line(MARGIN, W - MARGIN, p.y + 4, "#B8C2CC")
    p.text(W / 2 - 62, p.y + 18, "*** End of report ***", 8.5, "F2", "#52606D")
    p.y += 34
    p.signature(
        MARGIN,
        "S. Desai",
        ["Dr. S. Desai, MD (Pathology)", "Consultant Pathologist", "Reg. No. GMC-2012-45120"],
    )
    p.footer(foot, 1, 1, maroon)
    return build([p])


if __name__ == "__main__":
    OUT.write_bytes(lab_results())
    print(f"wrote {OUT}")
