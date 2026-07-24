"""Navigation package public surface."""
from agoda_crawler.navigation.search import (
    go_to_next_page,
    go_to_results_page,
    normalize_agoda_destination,
    search_hotels_via_ui,
    verify_hotel_results_page,
    _build_city_search_urls,
)

__all__ = [
    "go_to_next_page",
    "go_to_results_page",
    "normalize_agoda_destination",
    "search_hotels_via_ui",
    "verify_hotel_results_page",
    "_build_city_search_urls",
]
