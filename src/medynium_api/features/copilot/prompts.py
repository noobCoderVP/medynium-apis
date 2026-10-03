"""Versioned prompt files. The SHA-256 of each is stored with every answer and audit row (ADR-016, NFR-05)."""

import hashlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class Prompt:
    name: str
    text: str
    sha256: str

    @property
    def short_hash(self) -> str:
        return self.sha256[:12]


@cache
def load(name: str) -> Prompt:
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    return Prompt(name=name, text=text, sha256=hashlib.sha256(text.encode()).hexdigest())
