"""The in-scope drug list: the first 25 (drugs.yaml) followed by the India-focused additions (drugs_india.yaml).

The order is the id order (DRG-001, DRG-002, ...), so appending to the second file never moves an earlier id."""

from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
FILES = ("drugs.yaml", "drugs_india.yaml")


def load_drugs() -> list[dict[str, Any]]:
    drugs: list[dict[str, Any]] = []
    for name in FILES:
        drugs += yaml.safe_load((HERE / name).read_text(encoding="utf-8"))["drugs"]
    codes = [d["code"] for d in drugs]
    if len(codes) != len(set(codes)):
        raise ValueError("duplicate drug code in the catalog")
    return drugs
