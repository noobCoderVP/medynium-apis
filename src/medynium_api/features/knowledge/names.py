"""Pure name matching for knowledge search: drug names, Indian brands and section headings, forgiving of case,
plurals, prefixes and small typos. No I/O, so it is tested without Snowflake."""

import difflib
import re
from itertools import pairwise

from medynium_api.core.snowflake.queries import Row

WORD = re.compile(r"[a-z0-9][a-z0-9-]*")
MIN_PREFIX = 5  # "amlod" finds amlodipine; shorter prefixes match too much
MIN_FUZZY = 6  # typo tolerance only for longer words ("metformn" finds metformin)
FUZZY_CUTOFF = 0.84


def words(text: str) -> list[str]:
    return WORD.findall(text.lower())


def match_drugs(text: str, aliases: list[Row]) -> list[Row]:
    """Alias rows whose name appears in the text, exactly first, then as a prefix or a near-miss spelling."""
    tokens = words(text)
    grams = {*tokens, *(f"{a} {b}" for a, b in pairwise(tokens))}
    found = [r for r in aliases if r["name_text"] in grams]
    covered = {t for r in found for t in r["name_text"].split()}
    single = [r for r in aliases if " " not in r["name_text"]]
    names = sorted({r["name_text"] for r in single})
    for token in tokens:
        if token in covered or len(token) < MIN_PREFIX:
            continue
        hits = [n for n in names if n.startswith(token)]
        if not hits and len(token) >= MIN_FUZZY:
            hits = difflib.get_close_matches(token, names, n=2, cutoff=FUZZY_CUTOFF)
        found += [r for r in single if r["name_text"] in hits]
    return found


def suggest_drugs(text: str, display_names: list[str], count: int = 5) -> list[str]:
    """The indexed drugs closest to a name that matched nothing."""
    lowered = {n.lower(): n for n in display_names}
    hits: list[str] = []
    for token in words(text):
        if len(token) < 3:
            continue
        hits += [n for n in lowered if n.startswith(token) or token in n.split()]
        hits += difflib.get_close_matches(token, [w for n in lowered for w in n.split()], 3, 0.7)
    seen: list[str] = []
    for hit in hits:
        full = next((lowered[n] for n in lowered if hit == n or hit in n.split()), None)
        if full and full not in seen:
            seen.append(full)
    return seen[:count]


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def match_sections(wanted: str, names: list[str]) -> list[str]:
    """Section headings that fit what the user typed: the exact one (any case) first, then every heading that
    contains all the typed words, so "warnings" also finds "Boxed warning" and "Warnings and precautions"."""
    key = wanted.strip().lower()
    needed = [_stem(w) for w in words(key)]
    exact = [n for n in names if n.lower() == key]
    near = [
        n
        for n in names
        if n not in exact and needed and all(w in {_stem(x) for x in words(n)} for w in needed)
    ]
    return exact + near


FILLER = {
    "about", "does", "drug", "drugs", "from", "give", "have", "label", "that", "there", "this", "tell",
    "what", "when", "which", "with", "show", "find", "should", "sections", "section",
}  # fmt: skip


def _root(word: str) -> str:
    word = word[:-1] if word.endswith("s") and len(word) > 4 else word
    return word[:5]


def ungrounded(text: str, passages: list[str]) -> list[str]:
    """Content words in the query that appear in none of the passages. A word the index never mentions means the
    question is about something that is not indexed, however close the nearest text happens to score."""
    corpus = " ".join(passages).lower()
    content = [w for w in words(text) if len(w) >= 4 and w not in FILLER]
    return [w for w in content if _root(w) not in corpus]
