"""Playwright network routing helpers for crawler resource blocking."""
from typing import Iterable

from playwright.sync_api import BrowserContext

from agoda_crawler.config import BLOCK_RESOURCE_TYPES, BLOCK_URL_KEYWORDS
from agoda_crawler.utils.logging import log, log_ignored_error


def apply_resource_blocking(
    context: BrowserContext,
    resource_types: Iterable[str] = BLOCK_RESOURCE_TYPES,
    url_keywords: Iterable[str] = BLOCK_URL_KEYWORDS,
) -> None:
    blocked_types = frozenset(item.strip().lower() for item in resource_types if item)
    blocked_keywords = tuple(item.strip().lower() for item in url_keywords if item)
    if not blocked_types and not blocked_keywords:
        return

    def handle_route(route) -> None:
        request = route.request
        resource_type = (request.resource_type or "").lower()
        url = (request.url or "").lower()
        if resource_type in blocked_types or any(
            keyword in url for keyword in blocked_keywords
        ):
            route.abort()
            return
        route.continue_()

    try:
        context.route("**/*", handle_route)
        log(
            "Network: blocking "
            f"types={','.join(sorted(blocked_types)) or '-'} "
            f"keywords={len(blocked_keywords)}"
        )
    except Exception as exc:
        log_ignored_error("Network resource blocking setup failed", exc)
