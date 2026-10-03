"""limit/offset pagination and the {items, total, limit, offset} list shape."""

from dataclasses import dataclass
from typing import Annotated

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
