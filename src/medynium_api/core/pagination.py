"""limit/offset pagination and the {items, total, limit, offset} list shape."""

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Query
from pydantic import BaseModel


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class PageParams:
    limit: int = 50
    offset: int = 0


def page_params(
    limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


Paging = Annotated[PageParams, Depends(page_params)]


SortOrder = Literal["asc", "desc"]


def order_clause(
    sort: str | None, order: str, columns: dict[str, str], default: str, tiebreak: str
) -> str:
    """A safe ORDER BY body. `sort` is only ever a key of `columns`, so no request text reaches the SQL."""
    column = columns.get(sort or "", columns[default])
    direction = "ASC" if order == "asc" else "DESC"
    return f"{column} {direction} NULLS LAST, {tiebreak}"


def like(text: str) -> str:
    """A bound ILIKE pattern. The caller's own wildcard characters are dropped so they cannot widen a search."""
    return f"%{text.replace('%', '').replace('_', '').strip()}%"
