"""Worklist ranking, decided before the page is cut (fixes the old rank-by-flag-count-then-cut-to-10 order).

Priority is lexicographic: a recent emergency visit outranks any combination of lower flags, new results outrank a
medicine change, a medicine change outranks a new document. Ties break on the number of flags, then recency. The
weights are powers of two, so one higher flag always beats every lower flag together. The browser applies the same
order (worklist.tsx RANK); this module is the one place the order is decided.
"""

from collections.abc import Mapping

# Column -> weight. The SQL and the Python mirror are both built from this table.
WEIGHTS: dict[str, int] = {
    "HAS_RECENT_EMERGENCY": 8,
    "HAS_NEW_LAB": 4,
    "HAS_NEW_MEDICATION_CHANGE": 2,
    "HAS_NEW_DOCUMENT": 1,
}


def score_sql(prefix: str = "") -> str:
    """The attention score as a SQL expression over ANALYTICS.DASHBOARD_WORKLIST columns (`prefix` is a table alias)."""
    return " + ".join(f"IFF({prefix}{column}, {weight}, 0)" for column, weight in WEIGHTS.items())


def order_by_sql() -> str:
    return f"({score_sql()}) DESC, FLAG_COUNT DESC, LAST_CHANGE_DATE DESC, PATIENT_ID"


def score(flags: Mapping[str, bool]) -> int:
    """Python mirror of `score_sql`, used by tests to pin the order."""
    return sum(weight for column, weight in WEIGHTS.items() if flags.get(column))
