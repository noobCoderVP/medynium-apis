"""Apply data/scenarios/scenarios.yaml to CLINICAL (D-6). Delete + insert per patient id, so reruns are safe.

Run after 20_transform_clinical.sql (which truncates CLINICAL). Extra outpatient and hospital encounters
(with a claim each) are generated deterministically so utilisation counts look like a real history.
"""

import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sfadmin import build_vars, connect  # noqa: E402

SCENARIOS = Path(__file__).resolve().parent / "scenarios" / "scenarios.yaml"
TABLES = [
    "CLAIM",
    "CLINICAL_NOTE",
    "PROCEDURE",
    "LAB_RESULT",
    "MEDICATION",
    "DIAGNOSIS",
    "ENCOUNTER",
    "PATIENT",
]


def d(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def ts(value: Any, hour: int = 10) -> str:
    return (
        datetime.combine(d(value), datetime.min.time())
        .replace(hour=hour)
        .strftime("%Y-%m-%d %H:%M:%S")
    )


def visit_kind(cls: str) -> str:
    return {"emergency": "EMERGENCY", "inpatient": "HOSPITALIZATION"}.get(cls, "OUTPATIENT")


def main() -> None:
    data = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))["patients"]
    as_of = d(build_vars()["AS_OF"])
    conn = connect("MED_ADMIN", build_vars()["DB"])
    cur = conn.cursor()
    cur.execute(f"USE WAREHOUSE {build_vars()['WH']}")
    cur.execute("SELECT LOINC_CODE, TEST_NAME, UNIT, REF_LOW, REF_HIGH FROM CLINICAL.LAB_REFERENCE")
    refs = {r[0]: r for r in cur.fetchall()}
    ids = [p["id"] for p in data]
    marks = ", ".join(["%s"] * len(ids))
    for table in TABLES:
        cur.execute(f"DELETE FROM CLINICAL.{table} WHERE PATIENT_ID IN ({marks})", ids)

    counters = {"enc": 90000, "clm": 90000, "prc": 90000}
    for number, p in enumerate(data):
        rng = random.Random(f"seed-{p['id']}")
        cur.execute(
            "INSERT INTO CLINICAL.PATIENT (PATIENT_ID, SOURCE_ID, FULL_NAME, BIRTH_DATE, SEX, MARITAL_STATUS, CITY, STATE, PIN_CODE, PHONE) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                p["id"],
                f"seed-{p['id']}",
                p["name"],
                d(p["birth_date"]),
                p["sex"],
                "M",
                p["city"],
                p["state"],
                p["pin"],
                p["phone"],
            ),
        )
        enc_rows, claim_rows = [], []
        for e in p["encounters"]:
            end = ts(e["end"], 12) if e.get("end") else None
            enc_rows.append(
                (
                    e["id"],
                    p["id"],
                    ts(e["date"]),
                    end,
                    e["cls"],
                    visit_kind(e["cls"]),
                    e["desc"],
                    e.get("reason"),
                )
            )
        for c in p["claims"]:
            billed, approved = float(c["billed"]), float(c["approved"])
            status = c.get("status") or ("APPROVED" if approved >= billed * 0.95 else "PARTIAL")
            claim_rows.append(
                (
                    c["id"],
                    p["id"],
                    c["enc"],
                    d(c["date"]),
                    c["service"],
                    status,
                    billed,
                    approved,
                    max(0.0, billed - approved) if status == "SUBMITTED" else 0.0,
                )
            )

        if p.get("prev_visit"):  # the visit before the latest one: the baseline for "what changed"
            counters["enc"] += 1
            counters["clm"] += 1
            prev_id = f"ENC-{counters['enc']}"
            enc_rows.append(
                (
                    prev_id,
                    p["id"],
                    ts(p["prev_visit"]),
                    None,
                    "outpatient",
                    "OUTPATIENT",
                    "Outpatient consultation",
                    None,
                )
            )
            claim_rows.append(
                (
                    f"CLM-{counters['clm']}",
                    p["id"],
                    prev_id,
                    d(p["prev_visit"]),
                    "Outpatient consultation",
                    "APPROVED",
                    1800.0,
                    1710.0,
                    0.0,
                )
            )

        extra = p.get("extra", {})
        for kind, n, cls, desc in (("opd", extra.get("opd", 0), "outpatient", "Outpatient consultation"),
                                   ("hosp", extra.get("hosp", 0), "inpatient", "Hospital admission")):  # fmt: skip
            for _ in range(n):
                counters["enc"] += 1
                counters["clm"] += 1
                when = as_of - timedelta(days=rng.randint(215, 360))  # before any seeded visit
                end = ts(when + timedelta(days=rng.randint(2, 4)), 12) if kind == "hosp" else None
                enc_id = f"ENC-{counters['enc']}"
                enc_rows.append((enc_id, p["id"], ts(when), end, cls, visit_kind(cls), desc, None))
                billed = float(
                    rng.randint(90, 130) * 1000 if kind == "hosp" else rng.randint(14, 32) * 100
                )
                claim_rows.append(
                    (
                        f"CLM-{counters['clm']}",
                        p["id"],
                        enc_id,
                        when,
                        desc,
                        "APPROVED",
                        billed,
                        billed * 0.95,
                        0.0,
                    )
                )
        cur.executemany(
            "INSERT INTO CLINICAL.ENCOUNTER (ENCOUNTER_ID, PATIENT_ID, STARTED_AT, ENDED_AT, ENCOUNTER_CLASS, VISIT_KIND, DESCRIPTION, REASON_DESCRIPTION) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            enc_rows,
        )
        cur.executemany(
            "INSERT INTO CLINICAL.CLAIM (CLAIM_ID, PATIENT_ID, ENCOUNTER_ID, SERVICE_DATE, SERVICE_TEXT, STATUS, BILLED_INR, APPROVED_INR, OUTSTANDING_INR) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            claim_rows,
        )
        for _ in range(extra.get("proc", 0)):
            counters["prc"] += 1
            when = as_of - timedelta(days=rng.randint(215, 360))
            cur.execute(
                "INSERT INTO CLINICAL.PROCEDURE (PROCEDURE_ID, PATIENT_ID, DESCRIPTION, PERFORMED_AT, BASE_COST_INR) VALUES (%s,%s,%s,%s,%s)",
                (
                    f"PRC-{counters['prc']}",
                    p["id"],
                    "Diagnostic procedure",
                    ts(when),
                    rng.randint(5, 40) * 100,
                ),
            )
        cur.executemany(
            "INSERT INTO CLINICAL.DIAGNOSIS (DIAGNOSIS_ID, PATIENT_ID, CODE_SYSTEM, CODE, DESCRIPTION, ONSET_DATE, IS_ACTIVE) VALUES (%s,%s,'SNOMED-CT',%s,%s,%s,TRUE)",
            [(x["id"], p["id"], x["code"], x["desc"], d(x["onset"])) for x in p["diagnoses"]],
        )
        cur.executemany(
            "INSERT INTO CLINICAL.MEDICATION (MEDICATION_ID, PATIENT_ID, RXNORM_CODE, DESCRIPTION, DRUG_NAME, STRENGTH_TEXT, DOSE_TEXT, START_DATE, IS_ACTIVE, LAST_CHANGE_DATE, CHANGE_NOTE) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,TRUE,%s,%s)",
            [(m["id"], p["id"], m["rxnorm"], m["desc"], m["drug"], m["strength"], m["dose"], d(m["start"]),
              d(m["change_date"]) if m.get("change_date") else None, m.get("change_note")) for m in p["medications"]],
        )  # fmt: skip
        lab_rows = []
        for code, points in p.get("labs", {}).items():
            _, name, unit, low, high = refs[code]
            for when, value, lab_id in points:
                flag = (
                    "LOW"
                    if low is not None and value < low
                    else "HIGH"
                    if high is not None and value > high
                    else "NORMAL"
                )
                lab_rows.append(
                    (
                        lab_id,
                        p["id"],
                        ts(when, 8),
                        code,
                        name,
                        value,
                        unit,
                        low,
                        high,
                        flag,
                        "laboratory",
                    )
                )
        cur.executemany(
            "INSERT INTO CLINICAL.LAB_RESULT (LAB_ID, PATIENT_ID, OBSERVED_AT, LOINC_CODE, TEST_NAME, VALUE_NUM, UNIT, REF_LOW, REF_HIGH, ABNORMAL_FLAG, CATEGORY) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            lab_rows,
        )
        cur.executemany(
            "MERGE INTO CLINICAL.CLINICAL_NOTE t USING (SELECT %s AS NOTE_ID) s ON t.NOTE_ID = s.NOTE_ID "
            "WHEN NOT MATCHED THEN INSERT (NOTE_ID, PATIENT_ID, ENCOUNTER_ID, NOTE_TYPE, TITLE, NOTE_DATE, AUTHOR, BODY, CONTAINS_INJECTION) "
            "VALUES (s.NOTE_ID, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    n["id"],
                    p["id"],
                    n["enc"],
                    n["type"],
                    n["title"],
                    d(n["date"]),
                    n["author"],
                    n["body"],
                    bool(n.get("injection")),
                )
                for n in p["notes"]
            ],
        )
        print(
            f"seeded {p['id']} {p['name']} ({p['scenario']}): {len(enc_rows)} encounters, {len(claim_rows)} claims, {len(lab_rows)} labs"
        )
    conn.close()
    _ = number  # silence unused loop variable


if __name__ == "__main__":
    main()
