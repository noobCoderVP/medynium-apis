"""Write a realistic, styled 3-document demo set for a NEW patient, to show report upload creating labs, medicines and
diagnoses. Run: python data/sample_reports/gen_demo_new_patient.py [--name "Meera Iyer"]

Create the patient in the UI with the same name first: the name on a report is compared with the patient, and a
mismatch blocks approval until a doctor confirms it. Output goes to data/sample_reports/demo_new_patient/. Synthetic
only. Wording avoids "instructions" and similar, which the extractor treats as text aimed at an AI."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdfdraw import MARGIN, Page, W, build  # noqa: E402

OUT = Path(__file__).resolve().parent / "demo_new_patient"
RED, BLUE, GREEN = "#B3261E", "#1F5FBF", "#1B7F4B"
HIGH = {"color": RED, "bold": True, "tint": "#FDECEA"}
LOW = {"color": BLUE, "bold": True, "tint": "#EAF1FD"}
NOTE = "Synthetic demo document, not for clinical use"


# Sunrise Multispeciality Hospital: discharge summary ---------------------------------------------------------------
def discharge_summary(name: str) -> bytes:
    navy, stripe = "#12355B", "#2A9D8F"
    foot = f"{name}  |  UHID SMH-208841  |  Discharge Summary  |  {NOTE}"

    def top(page: Page) -> None:
        page.letterhead(
            "Sunrise Multispeciality Hospital",
            "NABH accredited  |  14 Karve Road, Kothrud, Pune 411038",
            ["Tel 020-5550-0142", "mail@sunrisehospital.example", "CIN U85110MH2008PTC000000"],
            navy,
            stripe,
        )

    p1 = Page()
    top(p1)
    p1.title("DISCHARGE SUMMARY", navy, "Department of General Medicine")
    p1.info_box(
        [
            ("Patient Name", name),
            ("UHID", "SMH-208841"),
            ("Age / Sex", "61 Years / Female"),
            ("IP Number", "IP-26-04417"),
            ("Date of Admission", "22/09/2026 10:40"),
            ("Date of Discharge", "27/09/2026"),
            ("Consultant", "Dr. Anil Kulkarni, MD"),
            ("Ward / Bed", "Medical Ward 3 / Bed 12"),
        ],
        navy,
        label_w=92,
    )
    p1.section("DIAGNOSES", navy)
    p1.table(
        [("Diagnosis", 270, "l"), ("ICD-10", 70, "l"), ("Status", 183, "l")],
        [
            [
                ("Diagnosis: Type 2 diabetes mellitus with hyperglycaemia", {"bold": True}),
                "E11.65",
                "Principal, active",
            ],
            ["Diagnosis: Chronic kidney disease stage 3a", "N18.31", "Secondary, chronic"],
            ["Diagnosis: Essential hypertension", "I10", "Secondary, chronic"],
            ["Diagnosis: Hypothyroidism", "E03.9", "Secondary, on treatment"],
            ["Diagnosis: Dyslipidaemia", "E78.5", "Secondary, on treatment"],
        ],
        navy,
    )
    p1.section("PRESENTING COMPLAINTS", navy)
    p1.para(
        "61 year old woman, known diabetic for 12 years and hypertensive for 9 years, presented with 3 days of "
        "increased thirst, frequent urination, fatigue and giddiness. No chest pain, fever or vomiting. Home fasting "
        "sugars had been 220 to 280 mg/dL over the past week."
    )
    p1.section("PAST HISTORY", navy)
    p1.para(
        "Type 2 diabetes since 2014, hypertension since 2017 and hypothyroidism since 2019. Chronic kidney disease "
        "was noted on routine labs in 2025. No known drug allergies. Non-smoker, no alcohol."
    )
    p1.section("EXAMINATION ON ADMISSION", navy)
    p1.tiles(
        [("BLOOD PRESSURE", "148/92 mmHg"), ("PULSE", "84 / min"), ("SpO2", "98 % (RA)"),
         ("TEMPERATURE", "98.4 F"), ("WEIGHT", "68 kg")],
        navy,
    )  # fmt: skip
    p1.para("Mild dehydration. Chest clear, heart sounds normal, abdomen soft. No pedal oedema.")
    p1.callout(
        "ALLERGIES AND ALERTS",
        "No known drug allergies. Renal impairment: avoid NSAIDs and review doses of renally cleared medicines. "
        "Glimepiride carries a risk of low sugars: counselled on symptoms and on carrying glucose.",
        "#B3261E",
        "#FDECEA",
    )
    p1.footer(foot, 1, 3, navy)

    p2 = Page()
    top(p2)
    p2.title("HOSPITAL COURSE AND INVESTIGATIONS", navy, f"{name}  |  UHID SMH-208841")
    p2.section("HOSPITAL COURSE", navy)
    p2.para(
        "Admitted with uncontrolled hyperglycaemia. Intravenous fluids and a basal-bolus insulin schedule were started "
        "and blood sugars settled to 140 to 180 mg/dL by day 3. Renal function was monitored daily; creatinine "
        "improved with hydration and was stable at discharge. Potassium was mildly raised on admission and was managed "
        "with diet. Urine routine showed no infection. Insulin was stopped on day 4 and oral agents were resumed."
    )
    p2.section("LABORATORY INVESTIGATIONS", navy)
    cols = [
        ("Test", 175, "l"),
        ("Result", 70, "r"),
        ("Flag", 40, "c"),
        ("Unit", 108, "l"),
        ("Reference", 130, "l"),
    ]
    p2.subhead("Sample collected: 22/09/2026 11:30  (on admission)", "#E3EEF6", navy)
    p2.table(
        cols,
        [
            ["HbA1c", ("8.4", HIGH), ("H", HIGH), "%", "< 7.0"],
            ["Fasting glucose", ("164", HIGH), ("H", HIGH), "mg/dL", "70 - 100"],
            ["Creatinine", ("1.5", HIGH), ("H", HIGH), "mg/dL", "0.6 - 1.3"],
            ["eGFR", ("47", LOW), ("L", LOW), "mL/min/1.73 m2", "> 60"],
            ["Potassium", ("5.2", HIGH), ("H", HIGH), "mmol/L", "3.5 - 5.0"],
            ["Sodium", "136", "", "mmol/L", "135 - 145"],
        ],
        navy,
    )
    p2.subhead("Repeat sample collected: 27/09/2026 07:50  (before discharge)", "#E3EEF6", navy)
    p2.table(
        cols,
        [
            ["Creatinine", ("1.4", HIGH), ("H", HIGH), "mg/dL", "0.6 - 1.3"],
            ["Potassium", "4.9", "", "mmol/L", "3.5 - 5.0"],
        ],
        navy,
    )
    p2.section("OTHER INVESTIGATIONS", navy)
    p2.bullets(
        [
            "ECG: sinus rhythm at 82/min, no acute ST-T changes.",
            "Chest X-ray: normal cardiac size, clear lung fields.",
            "Ultrasound abdomen: both kidneys normal in size with mildly increased echogenicity.",
            "Urine routine: glucose 3+, no protein, no pus cells.",
        ],
        navy,
    )
    p2.footer(foot, 2, 3, navy)

    p3 = Page()
    top(p3)
    p3.title("DISCHARGE MEDICATION AND FOLLOW UP", navy, f"{name}  |  UHID SMH-208841")
    p3.section("MEDICINES ON DISCHARGE", navy)
    p3.table(
        [
            ("#", 24, "c"),
            ("Medicine", 150, "l"),
            ("Strength", 62, "l"),
            ("Dose and frequency", 150, "l"),
            ("Remarks", 137, "l"),
        ],
        [
            ["1", ("Tab Metformin", {"bold": True}), "500 mg", "Twice daily", "After meals"],
            ["2", ("Tab Glimepiride", {"bold": True}), "1 mg", "Once daily", "Before breakfast"],
            ["3", ("Tab Telmisartan", {"bold": True}), "40 mg", "Once daily", "Morning"],
            ["4", ("Tab Amlodipine", {"bold": True}), "5 mg", "Once daily", "Morning"],
            ["5", ("Tab Atorvastatin", {"bold": True}), "20 mg", "Once daily", "At night"],
            ["6", ("Tab Levothyroxine", {"bold": True}), "75 mcg", "Once daily", "Empty stomach"],
            ["7", ("Tab Pantoprazole", {"bold": True}), "40 mg", "Once daily", "Before breakfast"],
        ],
        navy,
        row_h=20,
    )
    p3.section("ADVICE ON DISCHARGE", navy)
    p3.bullets(
        [
            "Diabetic diet with low salt and low potassium foods. Walk 30 minutes daily. Drink 2 litres of fluid a day.",
            "Check fasting and post-meal sugars at home and bring the record to review.",
            "Avoid painkillers of the NSAID group such as diclofenac and ibuprofen because of the kidney disease.",
            "Return at once for vomiting, breathlessness, very low sugars, reduced urine or swelling of the feet.",
        ],
        navy,
    )
    p3.callout(
        "FOLLOW UP",
        "Review in Medicine OPD in 1 week with HbA1c, creatinine, potassium and TSH reports. Nephrology opinion "
        "advised if creatinine rises above 1.8 mg/dL.",
        navy,
        "#E8F1F8",
    )
    p3.y += 6
    p3.signature(
        MARGIN,
        "A. Kulkarni",
        [
            "Dr. Anil Kulkarni, MD (Medicine)",
            "Senior Consultant, General Medicine",
            "Reg. No. MMC-2009-31877",
        ],
    )
    p3.footer(foot, 3, 3, navy)
    return build([p1, p2, p3])


# City Diagnostics Laboratory: lab report ---------------------------------------------------------------------------
def lab_report(name: str) -> bytes:
    maroon, stripe = "#7A1F2B", "#D6A24B"
    foot = f"{name}  |  Patient ID CDL-77310  |  Sample 2610020417  |  {NOTE}"

    def top(page: Page, number: int) -> None:
        page.letterhead(
            "City Diagnostics Laboratory",
            "NABL accredited (MC-3487)  |  Baner Road, Pune 411045",
            ["Tel 020-5550-0199", "reports@citydiagnostics.example"],
            maroon,
            stripe,
        )
        page.title(
            "LABORATORY REPORT", maroon, "" if number == 1 else "Abnormal results are highlighted"
        )
        page.info_box(
            [
                ("Patient Name", name),
                ("Patient ID", "CDL-77310"),
                ("Age / Sex", "61 Y / Female"),
                ("Referred by", "Dr. Anil Kulkarni"),
                ("Sample collected", "02/10/2026 07:45"),
                ("Reported on", "02/10/2026 13:20"),
            ],
            maroon,
            label_w=88,
        )
        if number == 1:
            page.barcode(W - MARGIN - 130, 84, 130, 15, 2610020417, "Sample ID 2610020417")

    cols = [
        ("Test name", 185, "l"),
        ("Result", 62, "r"),
        ("Flag", 38, "c"),
        ("Unit", 100, "l"),
        ("Biological reference interval", 138, "l"),
    ]
    sub = ("#F6E9EB", maroon)

    p1 = Page()
    top(p1, 1)
    p1.section("BIOCHEMISTRY", maroon)
    p1.subhead("GLYCATED HAEMOGLOBIN AND GLUCOSE", *sub)
    p1.table(
        cols,
        [
            ["HbA1c", ("7.6", HIGH), ("H", HIGH), "%", "< 7.0 (target for diabetes)"],
            ["Fasting glucose", ("138", HIGH), ("H", HIGH), "mg/dL", "70 - 100"],
        ],
        maroon,
    )
    p1.subhead("RENAL FUNCTION", *sub)
    p1.table(
        cols,
        [
            ["Creatinine", ("1.4", HIGH), ("H", HIGH), "mg/dL", "0.6 - 1.3"],
            ["eGFR", ("49", LOW), ("L", LOW), "mL/min/1.73 m2", "> 60"],
            ["Blood urea", ("46", HIGH), ("H", HIGH), "mg/dL", "15 - 40"],
            ["Uric acid", ("6.1", HIGH), ("H", HIGH), "mg/dL", "2.4 - 6.0"],
        ],
        maroon,
    )
    p1.subhead("ELECTROLYTES", *sub)
    p1.table(
        cols,
        [
            ["Potassium", ("5.1", HIGH), ("H", HIGH), "mmol/L", "3.5 - 5.0"],
            ["Sodium", "137", "", "mmol/L", "135 - 145"],
            ["Chloride", "102", "", "mmol/L", "98 - 107"],
        ],
        maroon,
    )
    p1.subhead("THYROID PROFILE", *sub)
    p1.table(
        cols,
        [
            ["TSH", ("7.2", HIGH), ("H", HIGH), "mIU/L", "0.4 - 4.0"],
            ["Free T4", "0.9", "", "ng/dL", "0.8 - 1.8"],
        ],
        maroon,
    )
    p1.para(
        "Comment: HbA1c reflects average glucose over the past 8 to 12 weeks. Values above 7.0 % indicate control "
        "above the usual target. Interpret with the clinical picture.",
        size=8,
        color="#52606D",
    )
    p1.footer(foot, 1, 2, maroon)

    p2 = Page()
    top(p2, 2)
    p2.subhead("LIPID PROFILE", *sub)
    p2.table(
        cols,
        [
            ["Total cholesterol", ("214", HIGH), ("H", HIGH), "mg/dL", "< 200"],
            ["LDL cholesterol", ("138", HIGH), ("H", HIGH), "mg/dL", "< 100"],
            ["HDL cholesterol", ("44", LOW), ("L", LOW), "mg/dL", "> 50"],
            ["Triglycerides", ("172", HIGH), ("H", HIGH), "mg/dL", "< 150"],
        ],
        maroon,
    )
    p2.section("HAEMATOLOGY", maroon)
    p2.subhead("COMPLETE BLOOD COUNT", *sub)
    p2.table(
        cols,
        [
            ["Haemoglobin", ("10.8", LOW), ("L", LOW), "g/dL", "12.0 - 15.5"],
            ["WBC count", "7.4", "", "10^3/uL", "4.0 - 11.0"],
            ["Platelet count", "248", "", "10^3/uL", "150 - 410"],
        ],
        maroon,
    )
    p2.line(MARGIN, W - MARGIN, p2.y + 4, "#B8C2CC")
    p2.text(W / 2 - 62, p2.y + 18, "*** End of report ***", 8.5, "F2", "#52606D")
    p2.y += 34
    p2.signature(
        MARGIN,
        "S. Rao",
        ["Dr. S. Rao, MD (Pathology)", "Consultant Pathologist", "Reg. No. MMC-2012-45120"],
    )
    p2.y -= 75
    p2.signature(
        W / 2 + 20,
        "R. Menon",
        ["Dr. R. Menon, MD (Biochemistry)", "Chief of Laboratory", "Reg. No. MMC-2008-27710"],
    )
    p2.para(
        "Results relate only to the sample tested. A clinical correlation is advised. Please contact the laboratory "
        "if a result does not fit the clinical picture.",
        size=7.5,
        color="#6B7785",
    )
    p2.footer(foot, 2, 2, maroon)
    return build([p1, p2])


# Lotus Clinic: outpatient note and prescription ---------------------------------------------------------------------
def clinic_note(name: str) -> bytes:
    green, stripe = "#1B6B4A", "#8FC9A6"
    foot = f"{name}  |  Lotus Clinic  |  OPD note 10/08/2026  |  {NOTE}"

    def top(page: Page) -> None:
        page.letterhead(
            "Lotus Clinic",
            "Dr. Neha Joshi, MD (Internal Medicine)  |  Reg. No. MMC-2011-40218",
            [
                "Shop 4, Lotus Plaza, Kothrud, Pune",
                "Tel 020-5550-0288",
                "Mon to Sat, 10 am to 7 pm",
            ],
            green,
            stripe,
        )

    p1 = Page()
    top(p1)
    p1.title("OUTPATIENT CONSULTATION NOTE", green, "Visit date 10/08/2026 11:15")
    p1.info_box(
        [
            ("Patient Name", name),
            ("OPD No.", "LC-9-2231"),
            ("Age / Sex", "61 Years / Female"),
            ("Visit type", "Follow up"),
            ("Date of visit", "10/08/2026 11:15"),
            ("Consultant", "Dr. Neha Joshi"),
        ],
        green,
    )
    p1.section("REASON FOR VISIT", green)
    p1.para(
        "Routine review of diabetes, blood pressure and thyroid. Reports tiredness and mild tingling in both feet for "
        "the past month. Occasional morning headache. No chest pain or breathlessness."
    )
    p1.section("VITALS AND SCREENING", green)
    p1.tiles(
        [("BLOOD PRESSURE", "150/94 mmHg"), ("PULSE", "80 / min"), ("WEIGHT", "69 kg"),
         ("RANDOM SUGAR", "236 mg/dL"), ("BMI", "28.4")],
        green,
    )  # fmt: skip
    p1.section("ASSESSMENT", green)
    p1.table(
        [("Diagnosis", 270, "l"), ("ICD-10", 70, "l"), ("Control", 183, "l")],
        [
            [
                "Diagnosis: Type 2 diabetes mellitus",
                "E11.9",
                ("Poor on current regimen", {"color": RED, "bold": True}),
            ],
            [
                "Diagnosis: Essential hypertension",
                "I10",
                ("Above target", {"color": RED, "bold": True}),
            ],
            ["Diagnosis: Hypothyroidism", "E03.9", "TSH due"],
            ["Diagnosis: Diabetic peripheral neuropathy", "E11.42", "New, mild"],
        ],
        green,
    )
    p1.callout(
        "CLINICAL IMPRESSION",
        "Sugar control is poor and blood pressure is above target. TSH was last checked 6 months ago. Kidney "
        "function to be rechecked as creatinine was borderline earlier. Foot sensation reduced to monofilament.",
        green,
        "#E7F3EC",
    )
    p1.footer(foot, 1, 2, green)

    p2 = Page()
    top(p2)
    p2.title("PRESCRIPTION", green, f"{name}  |  10/08/2026")
    p2.text(MARGIN, p2.y + 26, "Rx", 28, "F2", green)
    p2.y += 38
    p2.table(
        [
            ("#", 24, "c"),
            ("Medicine", 140, "l"),
            ("Strength", 60, "l"),
            ("Dose and frequency", 140, "l"),
            ("Started", 70, "l"),
            ("Note", 89, "l"),
        ],
        [
            [
                "1",
                ("Tab Metformin", {"bold": True}),
                "500 mg",
                "Twice daily after meals",
                "15/03/2018",
                "Continue",
            ],
            [
                "2",
                ("Tab Telmisartan", {"bold": True}),
                "40 mg",
                "Once daily, morning",
                "20/06/2017",
                "Continue",
            ],
            [
                "3",
                ("Tab Amlodipine", {"bold": True}),
                "5 mg",
                "Once daily",
                "10/08/2026",
                ("New", {"color": GREEN, "bold": True}),
            ],
            [
                "4",
                ("Tab Levothyroxine", {"bold": True}),
                "75 mcg",
                "Once daily, empty stomach",
                "02/11/2019",
                "Continue",
            ],
            [
                "5",
                ("Tab Atorvastatin", {"bold": True}),
                "20 mg",
                "Once daily at night",
                "10/08/2026",
                ("New", {"color": GREEN, "bold": True}),
            ],
            [
                "6",
                ("Tab Methylcobalamin", {"bold": True}),
                "1500 mcg",
                "Once daily",
                "10/08/2026",
                ("New", {"color": GREEN, "bold": True}),
            ],
        ],
        green,
        row_h=22,
    )
    p2.section("TESTS ADVISED", green)
    x = MARGIN
    for chip in ["HbA1c", "Creatinine", "eGFR", "Potassium", "TSH", "Lipid profile"]:
        w = len(chip) * 5.2 + 22
        p2.rect(x, p2.y, w, 20, fill="#E7F3EC", stroke=green)
        p2.text(x + 11, p2.y + 13.5, chip, 8.5, "F2", green)
        x += w + 8
    p2.y += 34
    p2.section("ADVICE", green)
    p2.bullets(
        [
            "Reduce rice, sweets and fried food. Walk 30 minutes daily.",
            "Check both feet every day and wear well fitting footwear.",
            "Keep a home blood pressure log, morning and evening, and bring it to the next visit.",
        ],
        green,
    )
    p2.callout("NEXT VISIT", "Review in 4 weeks with the reports above.", green, "#E7F3EC")
    p2.y += 4
    p2.signature(
        W - MARGIN - 190,
        "N. Joshi",
        ["Dr. Neha Joshi, MD", "Internal Medicine", "Reg. No. MMC-2011-40218"],
    )
    p2.footer(foot, 2, 2, green)
    return build([p1, p2])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--name", default="Meera Iyer", help="must equal the patient you create in the UI"
    )
    name = parser.parse_args().name
    OUT.mkdir(exist_ok=True)
    files = {
        "1_clinic_note_10-Aug-2026.pdf": clinic_note(name),
        "2_discharge_summary_27-Sep-2026.pdf": discharge_summary(name),
        "3_lab_report_02-Oct-2026.pdf": lab_report(name),
    }
    for filename, data in files.items():
        (OUT / filename).write_bytes(data)
    print(f"wrote {len(files)} PDFs for {name} to {OUT}")


if __name__ == "__main__":
    main()
