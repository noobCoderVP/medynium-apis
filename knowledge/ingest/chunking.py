"""Label JSON -> sections -> chunks (K-3). Pure functions, no I/O, easy to test.

Rules: split by label section so every chunk has a human section name; target about 1,800 characters
(roughly 450 tokens), never above 3,000; split on sentence boundaries, never mid-sentence; strip markup.
"""

import re

# openFDA field -> heading shown in citations, in priority order for the per-drug cap
SECTIONS = [
    ("boxed_warning", "Boxed warning"),
    ("contraindications", "Contraindications"),
    ("warnings_and_cautions", "Warnings and precautions"),
    ("warnings", "Warnings"),
    ("dosage_and_administration", "Dosage and administration"),
    ("use_in_specific_populations", "Use in specific populations"),
    ("drug_interactions", "Drug interactions"),
]
# Sections added after the first load (add_sections.py): what a drug is for, and its common adverse reactions. They are
# kept apart from SECTIONS so the chunk ids and the per-drug cap of the original corpus do not move.
NEW_SECTIONS = [
    ("indications_and_usage", "Indications and usage"),
    ("adverse_reactions", "Adverse reactions"),
]
# An over-the-counter label is a "Drug Facts" panel with different section names. Used only for drugs marked `otc` in the
# catalog, so the prescription chunks of the first 25 drugs (and the ids derived from them) are untouched.
OTC_SECTIONS = [
    ("do_not_use", "Do not use"),
    ("warnings", "Warnings"),
    ("ask_doctor", "Ask a doctor before use"),
    ("ask_doctor_or_pharmacist", "Ask a doctor or pharmacist before use"),
    ("stop_use", "Stop use and ask a doctor"),
    ("pregnancy_or_breast_feeding", "If pregnant or breast-feeding"),
    ("indications_and_usage", "Uses"),
    ("dosage_and_administration", "Directions"),
]
TARGET = 1800
MAX_CHARS = 3000
MAX_CHUNKS_PER_SECTION = 4
MAX_CHUNKS_PER_DRUG = 14
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\[(])")


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^\d+(\.\d+)*\s+(?=[A-Z][A-Z ,&-]{5,})", "", text)  # leading section number
    return text.replace(" .", ".").replace(" ,", ",")


def split_sentences(text: str, target: int = TARGET) -> list[str]:
    chunks: list[str] = []
    current = ""
    for sentence in SENTENCE.split(text):
        while (
            len(sentence) > MAX_CHARS
        ):  # a pathological run-on: cut at the last space before the limit
            cut = sentence.rfind(" ", 0, MAX_CHARS) or MAX_CHARS
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > target:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def label_chunks(
    record: dict, otc: bool = False, sections: list[tuple[str, str]] | None = None
) -> list[dict]:
    """Ordered chunks for one label: {section_key, section_name, index, text}."""
    out: list[dict] = []
    for key, name in sections or (OTC_SECTIONS if otc else SECTIONS):
        values = record.get(key)
        if not values:
            continue
        text = clean(" ".join(values))
        if len(text) < 80:
            continue
        for index, piece in enumerate(split_sentences(text)[:MAX_CHUNKS_PER_SECTION]):
            out.append({"section_key": key, "section_name": name, "index": index, "text": piece})
    return out[:MAX_CHUNKS_PER_DRUG]


def approx_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))
