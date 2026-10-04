"""A live look at one drug label from openFDA, for a drug the indexed snapshot does not hold (agentic upgrade, phase E).

Used only when the clinician asks for it by name. One fixed host, a strict drug-name pattern, a short timeout and no
redirects; the text that comes back is data (it is shown as a cited source and never read as instructions), and it is
marked as live so it is never confused with the stored snapshot. No new dependency: the standard library is enough."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger()
HOST = "https://api.fda.gov/drug/label.json"
DRUG = re.compile(r"^[A-Za-z][A-Za-z0-9 \-]{2,39}$")
TIMEOUT_SECONDS = 6
MAX_BYTES = 2_000_000
SECTIONS = (
    ("boxed_warning", "Boxed warning"),
    ("contraindications", "Contraindications"),
    ("warnings_and_cautions", "Warnings and precautions"),
    ("warnings", "Warnings"),
    ("drug_interactions", "Drug interactions"),
    ("use_in_specific_populations", "Use in specific populations"),
)
MAX_SECTION_CHARS = 1500
MAX_SECTIONS = 3


@dataclass(frozen=True)
class LiveSection:
    document_id: str
    title: str
    section: str
    version: str | None
    effective: str | None
    text: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, *args: Any, **kwargs: Any
    ) -> None:  # an unexpected redirect is an error, not a hop
        return None


def fetch_label(drug: str) -> list[LiveSection] | None:
    """Sections of the first matching label, or an empty list when openFDA has none. None when the lookup failed or the
    name is not a plain drug name; the caller says so honestly instead of guessing."""
    name = " ".join(drug.split())
    if not DRUG.match(name):
        return None
    search = f'openfda.generic_name:"{name}"+openfda.brand_name:"{name}"'
    url = f"{HOST}?search={urllib.parse.quote(search, safe=':"+')}&limit=1"
    try:
        opener = urllib.request.build_opener(_NoRedirect)
        request = urllib.request.Request(url, headers={"User-Agent": "medynium-demo"})  # noqa: S310 - fixed https host
        with opener.open(request, timeout=TIMEOUT_SECONDS) as r:
            raw = r.read(MAX_BYTES)
    except urllib.error.HTTPError as exc:
        return [] if exc.code == 404 else None  # openFDA answers 404 when nothing matches
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("openfda_unavailable", error=type(exc).__name__)
        return None
    try:
        label = json.loads(raw)["results"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return []
    meta = label.get("openfda") or {}
    title = (
        f"{(meta.get('brand_name') or [name])[0]} ({(meta.get('generic_name') or [name])[0]}) label"
    )
    set_id = str(label.get("set_id") or label.get("id") or "openfda")
    out: list[LiveSection] = []
    for key, heading in SECTIONS:
        parts = label.get(key)
        if not parts:
            continue
        text = " ".join(" ".join(parts).split())[:MAX_SECTION_CHARS]
        out.append(LiveSection(set_id, title, heading, str(label.get("version") or "") or None, label.get("effective_time"), text))  # fmt: skip
        if len(out) == MAX_SECTIONS:
            break
    return out
