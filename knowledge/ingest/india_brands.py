"""A-Z Medicines Dataset of India -> Indian brand names for the in-scope generics (K-4).

Single-ingredient compositions only: a brand whose composition has a second ingredient is skipped, so
"Augmentin" never maps to a single generic. The dataset's licence is unconfirmed, so it stays gitignored
and only brand names (not prices or manufacturers) are copied into the database.
"""

import csv
import re
from collections import Counter
from pathlib import Path

CSV = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "india_medicines"
    / "A_Z_medicines_dataset_of_India.csv"
)
FORMS = r"(tablet|tablets|capsule|capsules|syrup|suspension|injection|inhaler|cream|gel|drops|solution|respules|rotacap|expectorant|ointment|lotion|sachet|powder|\d)"
BRANDS_PER_DRUG = 4
STOP = {
    "angiotensin",
    "insulin",
    "vitamin",
    "calcium",
    "sodium",
    "oral",
    "forte",
    "plus",
    "duo",
    "cardio",
}


def brand_base(name: str) -> str:
    """'Glycomet 500 Tablet' -> 'glycomet'."""
    return (
        re.split(rf"\s+{FORMS}", name.strip(), maxsplit=1, flags=re.IGNORECASE)[0].strip().lower()
    )


def single_ingredient(row: dict[str, str]) -> str | None:
    if (row.get("short_composition2") or "").strip():
        return None
    composition = (row.get("short_composition1") or "").strip().lower()
    return re.sub(r"\s*\(.*\)\s*$", "", composition) or None


def build(aliases_by_code: dict[str, set[str]]) -> dict[str, list[str]]:
    """drug code -> the most common Indian brand names (not discontinued, single ingredient)."""
    if not CSV.exists():
        return {}
    wanted = {alias: code for code, aliases in aliases_by_code.items() for alias in aliases}
    counts: dict[str, Counter[str]] = {code: Counter() for code in aliases_by_code}
    with CSV.open(encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("Is_discontinued") or "").upper() == "TRUE":
                continue
            ingredient = single_ingredient(row)
            code = wanted.get(ingredient or "")
            brand = brand_base(row.get("name", ""))
            if (
                code
                and re.fullmatch(r"[a-z]{4,20}", brand)
                and brand not in wanted
                and brand not in STOP
            ):
                counts[code][brand] += 1
    return {code: [b for b, _ in c.most_common(BRANDS_PER_DRUG)] for code, c in counts.items()}
