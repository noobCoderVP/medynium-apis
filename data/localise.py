"""Localise the Synthea export for India and drop everything we do not load (D-4).

- Names, cities, PIN codes, phone numbers, hospital and clinician names come from a seeded generator,
  so the same Synthea patient always gets the same Indian identity.
- USD amounts become INR at a fixed rate (USD_INR_RATE, default 85) times an India price-level factor
  (INDIA_PRICE_FACTOR, default 0.06), so costs read as Indian prices rather than US prices in rupees.
- SSN, driver's licence, passport, race, ethnicity, birthplace, coordinates and income are never
  written to any output file (only the columns listed below are copied).

Output: data/synthea/localised/*.csv, byte-identical for the same input and seed.
"""

import csv
import hashlib
import os
import random
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from faker import Faker

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "synthea" / "out" / "csv"
DST = ROOT / "synthea" / "localised"
USD_INR = Decimal(os.environ.get("USD_INR_RATE", "85"))
# US prices are roughly 15 to 20 times Indian prices. Without this factor a US$500 visit would read as
# 42,500 rupees. 0.06 puts an outpatient visit near 2,500 rupees and a hospital stay near 1 lakh.
PRICE_FACTOR = Decimal(os.environ.get("INDIA_PRICE_FACTOR", "0.06"))
RATE = USD_INR * PRICE_FACTOR

CITIES = [  # city, state, first two PIN digits
    ("Ahmedabad", "Gujarat", "38"), ("Surat", "Gujarat", "39"), ("Vadodara", "Gujarat", "39"),
    ("Mumbai", "Maharashtra", "40"), ("Pune", "Maharashtra", "41"), ("Nagpur", "Maharashtra", "44"),
    ("Delhi", "Delhi", "11"), ("Jaipur", "Rajasthan", "30"), ("Lucknow", "Uttar Pradesh", "22"),
    ("Kanpur", "Uttar Pradesh", "20"), ("Bengaluru", "Karnataka", "56"), ("Mysuru", "Karnataka", "57"),
    ("Chennai", "Tamil Nadu", "60"), ("Coimbatore", "Tamil Nadu", "64"), ("Hyderabad", "Telangana", "50"),
    ("Kochi", "Kerala", "68"), ("Thiruvananthapuram", "Kerala", "69"), ("Kolkata", "West Bengal", "70"),
    ("Bhopal", "Madhya Pradesh", "46"), ("Indore", "Madhya Pradesh", "45"), ("Patna", "Bihar", "80"),
    ("Chandigarh", "Chandigarh", "16"), ("Bhubaneswar", "Odisha", "75"), ("Guwahati", "Assam", "78"),
]  # fmt: skip
HOSPITAL_KINDS = [
    "General Hospital",
    "Medical Centre",
    "Heart and Kidney Institute",
    "Clinic",
    "Multispeciality Hospital",
]

# Columns kept per file (everything else is dropped). Names ending in _INR style conversion are in MONEY.
KEEP = {
    "patients": ["Id", "BIRTHDATE", "DEATHDATE", "GENDER", "MARITAL", "FULL_NAME", "CITY", "STATE", "PIN_CODE", "PHONE"],
    "organizations": ["Id", "NAME"],
    "providers": ["Id", "ORGANIZATION", "NAME", "SPECIALITY"],
    "encounters": ["Id", "START", "STOP", "PATIENT", "ORGANIZATION", "PROVIDER", "ENCOUNTERCLASS", "CODE", "DESCRIPTION", "BASE_ENCOUNTER_COST", "TOTAL_CLAIM_COST", "PAYER_COVERAGE", "REASONCODE", "REASONDESCRIPTION"],
    "conditions": ["START", "STOP", "PATIENT", "ENCOUNTER", "SYSTEM", "CODE", "DESCRIPTION"],
    "medications": ["START", "STOP", "PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION", "BASE_COST", "DISPENSES", "TOTALCOST", "REASONCODE", "REASONDESCRIPTION"],
    "observations": ["DATE", "PATIENT", "ENCOUNTER", "CATEGORY", "CODE", "DESCRIPTION", "VALUE", "UNITS", "TYPE"],
    "procedures": ["START", "STOP", "PATIENT", "ENCOUNTER", "SYSTEM", "CODE", "DESCRIPTION", "BASE_COST", "REASONCODE", "REASONDESCRIPTION"],
    "claims": ["Id", "PATIENTID", "PROVIDERID", "SERVICEDATE", "APPOINTMENTID", "DIAGNOSIS1", "STATUS1", "STATUS2", "STATUSP", "OUTSTANDING1", "OUTSTANDING2", "OUTSTANDINGP"],
    "claims_transactions": ["ID", "CLAIMID", "PATIENTID", "TYPE", "AMOUNT", "METHOD", "FROMDATE", "PROCEDURECODE", "PAYMENTS", "OUTSTANDING", "NOTES"],
}  # fmt: skip
MONEY = {
    "encounters": ["BASE_ENCOUNTER_COST", "TOTAL_CLAIM_COST", "PAYER_COVERAGE"],
    "medications": ["BASE_COST", "TOTALCOST"],
    "procedures": ["BASE_COST"],
    "claims": ["OUTSTANDING1", "OUTSTANDING2", "OUTSTANDINGP"],
    "claims_transactions": ["AMOUNT", "PAYMENTS", "OUTSTANDING"],
}


def seed_for(value: str) -> int:
    return int(hashlib.sha256(value.encode()).hexdigest()[:12], 16)


def inr(value: str) -> str:
    if value in ("", None):
        return ""
    return str((Decimal(value) * RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def read(name: str) -> list[dict[str, str]]:
    with (SRC / f"{name}.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write(name: str, rows: list[dict[str, str]], columns: list[str]) -> None:
    DST.mkdir(parents=True, exist_ok=True)
    with (DST / f"{name}.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def identity(source_id: str, gender: str) -> dict[str, str]:
    fake = Faker("en_IN")
    fake.seed_instance(seed_for(source_id))
    rng = random.Random(seed_for("geo" + source_id))
    first = fake.first_name_male() if gender == "M" else fake.first_name_female()
    city, state, pin2 = rng.choice(CITIES)
    return {
        "FULL_NAME": f"{first} {fake.last_name()}",
        "CITY": city,
        "STATE": state,
        "PIN_CODE": f"{pin2}{rng.randint(0, 9999):04d}",
        "PHONE": f"+91 {rng.choice('6789')}{rng.randint(0, 999999999):09d}",
    }


def main() -> None:
    tables = {name: read(name) for name in KEEP if name != "observations"}

    for row in tables["patients"]:
        row.update(identity(row["Id"], row["GENDER"]))

    org_names: dict[str, str] = {}
    for row in tables["organizations"]:
        rng = random.Random(seed_for("org" + row["Id"]))
        city = rng.choice(CITIES)[0]
        row["NAME"] = f"{city} {rng.choice(HOSPITAL_KINDS)}"
        org_names[row["Id"]] = row["NAME"]

    for row in tables["providers"]:
        fake = Faker("en_IN")
        fake.seed_instance(seed_for("prov" + row["Id"]))
        first = fake.first_name_male() if row["GENDER"] == "M" else fake.first_name_female()
        row["NAME"] = f"Dr. {first} {fake.last_name()}"

    for name, columns in MONEY.items():
        for row in tables[name]:
            for column in columns:
                row[column] = inr(row[column])

    # Laboratory observations only (vital signs, surveys and exams are not used by the demo).
    observations = [r for r in read("observations") if r["CATEGORY"] == "laboratory"]

    for name, rows in tables.items():
        write(name, rows, KEEP[name])
    write("observations", observations, KEEP["observations"])
    print(f"Localised {len(KEEP)} files into {DST} (USD x {USD_INR} x {PRICE_FACTOR} = INR)")


if __name__ == "__main__":
    main()
