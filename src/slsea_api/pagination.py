"""Small pagination helpers shared by collection endpoints."""

from __future__ import annotations

from math import ceil

from fastapi import Request

from slsea_api.schemas import PageInfo, PageLinks

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def page_metadata(
    request: Request,
    *,
    page: int,
    page_size: int,
    total_items: int,
) -> tuple[PageInfo, PageLinks]:
    total_pages = ceil(total_items / page_size) if total_items else 0

    def url_for(target_page: int) -> str:
        # include_query_params keeps every active filter and changes only pagination.
        return str(request.url.include_query_params(page=target_page, page_size=page_size))

    info = PageInfo(
        number=page,
        size=page_size,
        total_items=total_items,
        total_pages=total_pages,
    )
    links = PageLinks(
        self=url_for(page),
        next=url_for(page + 1) if page < total_pages else None,
        previous=url_for(page - 1) if page > 1 and total_pages else None,
    )
    return info, links
